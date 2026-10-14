"""PostgreSQL job leases with monotonically increasing fencing tokens.

Execution is at least once. A lease does not by itself stop a paused or partitioned
worker from writing later; every committed write therefore re-checks the fencing token
inside the same transaction (see `fenced`).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.contracts import RunState, check_transition


class StaleOwner(RuntimeError):
    """The caller's lease was superseded or released. Its writes must not commit."""


@dataclass(frozen=True)
class Lease:
    run_id: str
    worker_id: str
    token: int
    resume_payload: dict[str, Any] | None


def add_event(conn_or_cur: Any, run_id: str, event_type: str, payload: dict) -> None:
    conn_or_cur.execute(
        "INSERT INTO run_events (run_id, event_type, payload) VALUES (%s, %s, %s)",
        (run_id, event_type, Jsonb(payload)),
    )


def enqueue_run(conn: psycopg.Connection, run_id: str, workspace_id: str, brief: dict) -> None:
    with conn.transaction():
        conn.execute(
            "INSERT INTO runs (run_id, workspace_id, state, brief) VALUES (%s, %s, %s, %s)",
            (run_id, workspace_id, RunState.QUEUED.value, Jsonb(brief)),
        )
        conn.execute("INSERT INTO run_jobs (run_id, state) VALUES (%s, 'QUEUED')", (run_id,))
        add_event(conn, run_id, "run_created", {})


_CLAIM_SQL = """
UPDATE run_jobs AS j
SET state = 'LEASED',
    lease_owner = %(worker)s,
    lease_expires_at = now() + make_interval(secs => %(secs)s),
    fencing_token = j.fencing_token + 1,
    attempts = j.attempts + 1
WHERE j.run_id = (
    SELECT run_id FROM run_jobs
    WHERE ((state = 'QUEUED' AND available_at <= now())
           OR (state = 'LEASED' AND lease_expires_at < now()))
      AND attempts < max_attempts
      AND (%(run_id)s::text IS NULL OR run_id = %(run_id)s::text)
    ORDER BY available_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING j.run_id, j.fencing_token, j.resume_payload
"""


def claim(
    conn: psycopg.Connection, worker_id: str, lease_seconds: float, run_id: str | None = None
) -> Lease | None:
    """Claim a queued job, or take over one whose lease expired (database clock only)."""
    row = conn.execute(
        _CLAIM_SQL, {"worker": worker_id, "secs": float(lease_seconds), "run_id": run_id}
    ).fetchone()
    if row is None:
        return None
    return Lease(row["run_id"], worker_id, row["fencing_token"], row["resume_payload"])


@contextmanager
def fenced(conn: psycopg.Connection, lease: Lease) -> Iterator[psycopg.Cursor]:
    """Transaction that commits only if `lease` is still the current owner.

    FOR SHARE blocks a concurrent claim (which needs FOR UPDATE) until this transaction
    ends, so a takeover either happens before the check (and the write is rejected) or
    after the commit (and the new owner sees the write).
    """
    with conn.transaction(), conn.cursor() as cur:
        row = cur.execute(
            "SELECT fencing_token, state FROM run_jobs WHERE run_id = %s FOR SHARE",
            (lease.run_id,),
        ).fetchone()
        if row is None or row["state"] != "LEASED" or row["fencing_token"] != lease.token:
            raise StaleOwner(
                f"run {lease.run_id}: token {lease.token} is no longer current "
                f"(db token={row and row['fencing_token']}, state={row and row['state']})"
            )
        yield cur


def heartbeat(conn: psycopg.Connection, lease: Lease, lease_seconds: float) -> None:
    row = conn.execute(
        """UPDATE run_jobs SET lease_expires_at = now() + make_interval(secs => %s)
           WHERE run_id = %s AND fencing_token = %s AND state = 'LEASED'
           RETURNING run_id""",
        (float(lease_seconds), lease.run_id, lease.token),
    ).fetchone()
    if row is None:
        raise StaleOwner(f"heartbeat rejected for run {lease.run_id} token {lease.token}")


def set_run_state(cur: psycopg.Cursor, run_id: str, target: RunState) -> None:
    """Validated transition; a no-op when already in `target` (re-executed nodes)."""
    row = cur.execute("SELECT state FROM runs WHERE run_id = %s FOR UPDATE", (run_id,)).fetchone()
    current = RunState(row["state"])
    if current == target:
        return
    check_transition(current, target)
    cur.execute(
        "UPDATE runs SET state = %s, updated_at = now() WHERE run_id = %s", (target.value, run_id)
    )
    add_event(cur, run_id, "state_changed", {"from": current.value, "to": target.value})


def release_to_wait(conn: psycopg.Connection, lease: Lease, kind: str) -> None:
    """Approval waits hold no lease and no worker; resumption is scheduled by the decision."""
    target = RunState.AWAITING_PLAN_APPROVAL if kind == "plan" else RunState.AWAITING_REPORT_APPROVAL
    with fenced(conn, lease) as cur:
        set_run_state(cur, lease.run_id, target)
        cur.execute(
            """UPDATE run_jobs SET state = 'WAITING', waiting_for = %s, resume_payload = NULL,
                   lease_owner = NULL, lease_expires_at = NULL
               WHERE run_id = %s""",
            (kind, lease.run_id),
        )


def complete(conn: psycopg.Connection, lease: Lease) -> None:
    with fenced(conn, lease) as cur:
        cur.execute(
            """UPDATE run_jobs SET state = 'DONE', lease_owner = NULL, lease_expires_at = NULL
               WHERE run_id = %s""",
            (lease.run_id,),
        )


def fail(conn: psycopg.Connection, lease: Lease, step: str, reason: str) -> None:
    with fenced(conn, lease) as cur:
        set_run_state(cur, lease.run_id, RunState.FAILED)
        cur.execute(
            """UPDATE run_jobs SET state = 'FAILED', lease_owner = NULL, lease_expires_at = NULL
               WHERE run_id = %s""",
            (lease.run_id,),
        )
        add_event(cur, lease.run_id, "step_failed", {"step": step, "reason": reason})


def abandon_unfinished_tool_executions(conn: psycopg.Connection, lease: Lease) -> int:
    """Reconciliation on takeover: calls started by a previous owner never recorded a
    result. They may still have run (and cost money) at the provider; mark them honestly."""
    with fenced(conn, lease) as cur:
        cur.execute(
            """UPDATE tool_executions SET status = 'abandoned', finished_at = now()
               WHERE run_id = %s AND status = 'started' AND fencing_token < %s""",
            (lease.run_id, lease.token),
        )
        return cur.rowcount
