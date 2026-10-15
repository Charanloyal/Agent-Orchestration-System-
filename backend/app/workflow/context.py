"""Execution context for one leased worker pass over one run."""

import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import AgentSuite
from app.billing.meter import BudgetMeter
from app.config import Settings
from app.contracts import Brief
from app.contracts.run_state import RunState
from app.providers.search import SearchProvider
from app.services.events import append_event, set_run_state
from app.tools.fetcher import Fetcher
from app.workers import jobs
from app.workers.jobs import Lease, StaleOwner


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

    def transition(self, target: RunState, reason: str | None = None) -> None:
        with self.fenced() as session:
            set_run_state(session, self.run_id, target, reason)

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self.fenced() as session:
            append_event(session, self.run_id, self.workspace_id, event_type, payload)

    def crash_if(self, point: str) -> None:
        """Fault injection for recovery tests; inert outside dev/test."""
        if self.settings.env != "prod" and self.settings.crash_at == point:
            os._exit(137)
