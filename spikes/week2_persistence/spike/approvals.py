"""Human decisions bound to the exact artifact version and digest (FR-04).

Authentication and role checks are out of scope for this spike; `decided_by` is recorded
but not authorized. In the product, permission is checked at decision time in this same
transaction.
"""

import uuid

import psycopg
from psycopg.types.json import Jsonb

from app.contracts import ApprovalDecision, check_decision_matches
from spike.leases import add_event

_TABLES = {"plan": "plan_versions", "report": "report_versions"}


class NotAwaitingDecision(RuntimeError):
    pass


def decide(
    conn: psycopg.Connection,
    run_id: str,
    *,
    kind: str,
    version: int,
    digest: str,
    decision: str,
    decided_by: str,
) -> str:
    """Record a decision and durably schedule resumption, in one transaction."""
    request = ApprovalDecision(
        artifact_kind=kind, artifact_version=version, artifact_digest=digest, decision=decision
    )
    with conn.transaction():
        job = conn.execute(
            "SELECT state, waiting_for FROM run_jobs WHERE run_id = %s FOR UPDATE", (run_id,)
        ).fetchone()
        if job is None or job["state"] != "WAITING" or job["waiting_for"] != kind:
            raise NotAwaitingDecision(f"run {run_id} is not awaiting a {kind} decision")

        current = conn.execute(
            f"SELECT version, body FROM {_TABLES[kind]} WHERE run_id = %s "
            "ORDER BY version DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        # Recomputes the digest from the stored body rather than trusting a stored digest.
        check_decision_matches(request, current["version"], current["body"])

        approval_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO approvals (approval_id, run_id, artifact_kind, artifact_version,
                   artifact_digest, decision, decided_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (approval_id, run_id, kind, version, digest, decision, decided_by),
        )
        conn.execute(
            """UPDATE run_jobs SET state = 'QUEUED', waiting_for = NULL, available_at = now(),
                   resume_payload = %s
               WHERE run_id = %s""",
            (Jsonb({"approval_id": approval_id}), run_id),
        )
        add_event(
            conn, run_id, "decision_recorded", {"kind": kind, "version": version, "decision": decision}
        )
    return approval_id


def load_approval(conn: psycopg.Connection, approval_id: str) -> dict:
    row = conn.execute("SELECT * FROM approvals WHERE approval_id = %s", (approval_id,)).fetchone()
    if row is None:
        raise LookupError(f"approval {approval_id} not found")
    return row
