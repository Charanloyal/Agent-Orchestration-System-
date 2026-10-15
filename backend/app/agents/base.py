"""Agent roles behind narrow, typed interfaces. Agents never touch the database or the
network directly: research goes through ResearchTools, which enforces policy and records
every external call."""

from dataclasses import dataclass
from typing import Protocol

from app.contracts import Brief, Plan, PlanTask, ResearcherOutput, ReviewerOutput, ReviewFinding, WriterOutput
from app.providers.search import SearchHit


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    source_id: str
    text: str


@dataclass(frozen=True)
class EvidenceView:
    evidence_id: str
    source_id: str
    task_id: str
    title: str | None
    url: str | None
    published_on: str | None
    text: str


class ResearchTools(Protocol):
    def search(self, query: str) -> list[SearchHit]: ...

    def search_uploads(self, query: str) -> list[SearchHit]: ...

    def collect(self, hit: SearchHit) -> list[EvidenceRef]: ...


@dataclass(frozen=True)
class AgentCall[T]:
    output: T
    attempts: int


class Planner(Protocol):
    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]: ...


class Researcher(Protocol):
    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]: ...


class Writer(Protocol):
    def write(
        self,
        brief: Brief,
        plan: Plan,
        evidence: list[EvidenceView],
        *,
        report_version: int,
        findings: list[ReviewFinding],
    ) -> AgentCall[WriterOutput]: ...


class Reviewer(Protocol):
    def review(
        self,
        brief: Brief,
        plan: Plan,
        draft: WriterOutput,
        evidence: list[EvidenceView],
        *,
        review_round: int,
    ) -> AgentCall[ReviewerOutput]: ...


@dataclass(frozen=True)
class AgentSuite:
    planner: Planner
    researcher: Researcher
    writer: Writer
    reviewer: Reviewer
