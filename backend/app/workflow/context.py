"""Execution context for one leased worker pass over one run."""

import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import AgentSuite
from app.billing.meter import BudgetMeter
from app.config import Settings
from app.contracts import Brief
from app.contracts.run_state import TERMINAL_STATES, RunState
from app.db.models import Run
from app.providers.search import SearchProvider
from app.services.events import append_event, set_run_state
from app.tools.fetcher import Fetcher
from app.workers import jobs
from app.workers.jobs import Lease, StaleOwner
from app.workflow.errors import RunStopped


@dataclass
class RunContext:
    settings: Settings
    sm: sessionmaker[Session]
    lease: Lease
    workspace_id: uuid.UUID
    brief: Brief
    agents: AgentSuite
    search: SearchProvider
    fetcher: Fetcher
    alive: threading.Event = field(default_factory=threading.Event)
    meter: BudgetMeter = field(init=False)

    def __post_init__(self) -> None:
        self.alive.set()
        self.meter = BudgetMeter(self)

    @property
    def run_id(self) -> uuid.UUID:
        return self.lease.run_id

    @contextmanager
    def fenced(self) -> Iterator[Session]:
        if not self.alive.is_set():
            raise StaleOwner(f"lease for run {self.run_id} was lost (heartbeat failed)")
        with jobs.fenced(self.sm, self.lease) as session:
            yield session

    def check_continue(self, session: Session) -> None:
        """Called at every boundary that starts new work (step start, tool call, billable
        call). Raises RunStopped if a human asked to cancel or the segment deadline passed.
        Results of calls already in flight are still recorded (PRD §3.5)."""
        state, expired = session.execute(
            select(Run.state, Run.deadline_at < func.now()).where(Run.id == self.run_id)
        ).one()
        if state == RunState.CANCEL_REQUESTED:
            raise RunStopped(RunState.CANCELLED, "Cancelled at the next step boundary")
        if expired and state not in TERMINAL_STATES:
            raise RunStopped(RunState.EXPIRED, "Run deadline passed before the work finished")

    def transition(self, target: RunState, reason: str | None = None) -> None:
        with self.fenced() as session:
            self.check_continue(session)
            set_run_state(session, self.run_id, target, reason)

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self.fenced() as session:
            append_event(session, self.run_id, self.workspace_id, event_type, payload)

    def crash_if(self, point: str) -> None:
        """Fault injection for recovery tests; inert outside dev/test."""
        if self.settings.env != "prod" and self.settings.crash_at == point:
            os._exit(137)
