"""Periodic housekeeping run by every worker between passes. Safe under concurrency: rows
are locked with SKIP LOCKED, so workers never block each other or a decision in progress."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.run_state import RunState
from app.db.models import Run, RunJob, ToolExecution
from app.services.events import append_event, set_run_state


def expire_overdue_waits(sm: sessionmaker[Session], batch: int = 50) -> int:
    """Approval waits past their deadline become EXPIRED (PRD §3.5). A decision racing this
    either commits first (the job is no longer WAITING) or finds the run already expired."""
    with sm() as session, session.begin():
        jobs = session.scalars(
            select(RunJob)
            .where(RunJob.state == "WAITING", RunJob.wait_deadline_at < func.now())
            .order_by(RunJob.wait_deadline_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            set_run_state(
                session, job.run_id, RunState.EXPIRED, f"No {job.waiting_for} decision before the deadline"
            )
            job.state, job.waiting_for, job.wait_deadline_at, job.resume_payload = "DONE", None, None, None
    return len(jobs)


def reap_exhausted_jobs(sm: sessionmaker[Session], batch: int = 50) -> int:
    """Each claim counts an attempt, so a job whose lease expired after its last allowed
    attempt (a worker crashing on the same step every time) is never claimed again. Fail it
    visibly instead of leaving it stuck, fence off any zombie owner, and mark its in-flight
    tool calls abandoned. A pending cancellation still wins."""
    with sm() as session, session.begin():
        jobs = session.scalars(
            select(RunJob)
            .where(
                RunJob.state == "LEASED",
                RunJob.lease_expires_at < func.now(),
                RunJob.attempts >= RunJob.max_attempts,
            )
            .limit(batch)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            run = session.get(Run, job.run_id)
            assert run is not None
            reason = f"worker crashed or stalled on {job.attempts} consecutive attempts"
            cancelling = run.state == RunState.CANCEL_REQUESTED
            if cancelling:
                set_run_state(session, job.run_id, RunState.CANCELLED, "Cancelled; the worker had stopped")
            else:
                set_run_state(session, job.run_id, RunState.FAILED, f"worker: {reason}")
                append_event(
                    session, job.run_id, run.workspace_id, "step_failed", {"step": "worker", "reason": reason}
                )
            session.execute(
                update(ToolExecution)
                .where(ToolExecution.run_id == job.run_id, ToolExecution.status == "started")
                .values(status="abandoned", finished_at=func.now())
            )
            job.state = "DONE" if cancelling else "FAILED"
            job.lease_owner, job.lease_expires_at, job.last_error = None, None, reason
            job.fencing_token += 1
    return len(jobs)
