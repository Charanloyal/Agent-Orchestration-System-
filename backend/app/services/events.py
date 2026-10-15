"""Run timeline events and validated state transitions."""

import uuid
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.contracts.run_state import RunState, check_transition
from app.db.models import Run, RunEvent

NOTIFY_CHANNEL = "aos_run_events"


def append_event(
    session: Session, run_id: uuid.UUID, workspace_id: uuid.UUID, event_type: str, payload: dict[str, Any]
) -> None:
    """Append to the timeline in the caller's transaction. Payloads are structured summaries
    only: never prompts, model output, or source text."""
    session.add(RunEvent(run_id=run_id, workspace_id=workspace_id, event_type=event_type, payload=payload))
    session.execute(
        text("SELECT pg_notify(:channel, :run_id)"), {"channel": NOTIFY_CHANNEL, "run_id": str(run_id)}
    )


def set_run_state(session: Session, run_id: uuid.UUID, target: RunState, reason: str | None = None) -> bool:
    """Validated transition (ADR 0006). Returns False if already in `target` (re-executed node)."""
    run = session.execute(select(Run).where(Run.id == run_id).with_for_update()).scalar_one()
    current = RunState(run.state)
    if current == target:
        return False
    check_transition(current, target)
    values: dict[str, Any] = {"state": target.value}
    if reason is not None:
        values["outcome_reason"] = reason[:500]
    session.execute(update(Run).where(Run.id == run_id).values(**values))
    payload: dict[str, Any] = {"from": current.value, "to": target.value}
    if reason:
        payload["reason"] = reason[:500]
    append_event(session, run_id, run.workspace_id, "state_changed", payload)
    return True
