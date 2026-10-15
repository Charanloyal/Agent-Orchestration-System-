"""Periodic housekeeping run by every worker between passes. Safe under concurrency: rows
are locked with SKIP LOCKED, so workers never block each other or a decision in progress."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.run_state import RunState
from app.db.models import RunJob
from app.services.events import set_run_state


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
