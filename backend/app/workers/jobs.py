"""PostgreSQL job leases with monotonically increasing fencing tokens (ADR 0008).

Execution is at least once. A lease alone does not stop a paused worker from writing later,
so every committed write re-checks the fencing token inside the same transaction (`fenced`).
All times use the database clock.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RunJob, ToolExecution


class StaleOwner(RuntimeError):
    """The caller's lease was superseded or released. Its writes must not commit."""


@dataclass(frozen=True)
class Lease:
    run_id: uuid.UUID
    worker_id: str
    token: int
    attempts: int
    resume_payload: dict[str, Any] | None


_CLAIM_SQL = text(
    """
    UPDATE run_jobs AS j
    SET state = 'LEASED',
        lease_owner = :worker,
        lease_expires_at = now() + make_interval(secs => :secs),
        fencing_token = j.fencing_token + 1,
        attempts = j.attempts + 1
    WHERE j.run_id = (
        SELECT run_id FROM run_jobs
        WHERE ((state = 'QUEUED' AND available_at <= now())
               OR (state = 'LEASED' AND lease_expires_at < now()))
          AND attempts < max_attempts
          AND (CAST(:run_id AS uuid) IS NULL OR run_id = CAST(:run_id AS uuid))
        ORDER BY available_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING j.run_id, j.fencing_token, j.attempts, j.resume_payload
    """
)


def claim(
    sm: sessionmaker[Session], worker_id: str, lease_seconds: float, run_id: uuid.UUID | None = None
) -> Lease | None:
    """Claim a queued job or take over one whose lease expired."""
    with sm() as session, session.begin():
        row = session.execute(
            _CLAIM_SQL,
            {"worker": worker_id, "secs": float(lease_seconds), "run_id": str(run_id) if run_id else None},
        ).one_or_none()
    if row is None:
        return None
    return Lease(row.run_id, worker_id, row.fencing_token, row.attempts, row.resume_payload)


@contextmanager
def fenced(sm: sessionmaker[Session], lease: Lease) -> Iterator[Session]:
    """A transaction that commits only if `lease` is still the current owner.

    FOR SHARE blocks a concurrent takeover (which needs FOR UPDATE) until this transaction
    ends: a takeover happens either before the check (write rejected) or after the commit.
    """
    with sm() as session, session.begin():
        row = session.execute(
            select(RunJob.fencing_token, RunJob.state)
            .where(RunJob.run_id == lease.run_id)
            .with_for_update(read=True)
        ).one_or_none()
        if row is None or row.state != "LEASED" or row.fencing_token != lease.token:
            raise StaleOwner(f"run {lease.run_id}: lease token {lease.token} is no longer current")
        yield session


def heartbeat(sm: sessionmaker[Session], lease: Lease, lease_seconds: float) -> None:
    with sm() as session, session.begin():
        updated = session.execute(
            update(RunJob)
            .where(
                RunJob.run_id == lease.run_id,
                RunJob.fencing_token == lease.token,
                RunJob.state == "LEASED",
            )
            .values(lease_expires_at=func.now() + timedelta(seconds=lease_seconds))
            .returning(RunJob.run_id)
        ).one_or_none()
    if updated is None:
        raise StaleOwner(f"heartbeat rejected for run {lease.run_id}")


def _release(session: Session, lease: Lease, **values: Any) -> None:
    session.execute(
        update(RunJob)
        .where(RunJob.run_id == lease.run_id)
        .values(lease_owner=None, lease_expires_at=None, **values)
    )


def release_to_wait(session: Session, lease: Lease, kind: str, wait_hours: float) -> None:
    """Approval waits hold no lease; a decision re-queues the job (call inside `fenced`).
    Attempts restart per segment so human waits never consume the retry budget."""
    _release(
        session,
        lease,
        state="WAITING",
        waiting_for=kind,
        resume_payload=None,
        attempts=0,
        wait_deadline_at=func.now() + timedelta(hours=wait_hours),
    )


def mark_done(session: Session, lease: Lease) -> None:
    _release(session, lease, state="DONE", waiting_for=None, wait_deadline_at=None)


def mark_failed(session: Session, lease: Lease, reason: str) -> None:
    _release(session, lease, state="FAILED", waiting_for=None, last_error=reason[:500])


def requeue_with_backoff(session: Session, lease: Lease, delay_seconds: float, reason: str) -> None:
    _release(
        session,
        lease,
        state="QUEUED",
        available_at=func.now() + timedelta(seconds=delay_seconds),
        last_error=reason[:500],
    )


def abandon_unfinished_tool_executions(session: Session, lease: Lease) -> int:
    """Calls started by an earlier owner never recorded a result. They may still have run,
    and cost money, at the provider. Mark them honestly instead of pretending otherwise."""
    result = session.execute(
        update(ToolExecution)
        .where(
            ToolExecution.run_id == lease.run_id,
            ToolExecution.status == "started",
            ToolExecution.fencing_token < lease.token,
        )
        .values(status="abandoned", finished_at=func.now())
        .returning(ToolExecution.id)
    )
    return len(result.all())
