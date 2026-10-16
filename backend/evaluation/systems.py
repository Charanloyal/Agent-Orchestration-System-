"""Systems under evaluation and the fault-injecting providers fixtures need (ADR 0017).

- A, orchestrated: the production agent suite (planner, parallel researchers, writer, reviewer).
- B, single-agent baseline: same tools, corpus, budget and allowlist. A fixed one-task plan
  collects evidence for every research question without any model, then one writer call
  produces the whole report. No separate planner, researcher or reviewer agent.
- C, reviewer ablation: A with a pass-through reviewer (no deterministic checks, no model
  review, so no revision round).

Every system still passes the workflow's human approval gates; the harness answers them as a
simulated human, which is recorded in the results.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Literal, NoReturn

from app.agents.base import AgentCall, AgentSuite, EvidenceView, ResearchTools
from app.agents.fake import fake_agents
from app.config import Settings
from app.contracts import (
    Brief,
    OutlineSection,
    Plan,
    PlanTask,
    ResearcherOutput,
    ResearchFinding,
    ReviewerOutput,
    ReviewFinding,
    WriterOutput,
)
from app.policy.tools import allowed_tools
from app.providers.llm import LlmProvider, LlmResult
from app.providers.search import SearchProvider, SearchResponse
from app.tools.fetcher import FetchError, FetchResult
from app.workers.runner import build_agents
from app.workflow.context import RunContext
from app.workflow.errors import TransientError

SystemId = Literal["A", "B", "C"]
SYSTEMS: dict[SystemId, str] = {
    "A": "orchestrated: planner, parallel researchers, writer, reviewer",
    "B": "single-agent baseline: fixed collection plan, one writer call, no reviewer",
    "C": "reviewer ablation: system A with a pass-through reviewer",
}
Mode = Literal["fake", "llm"]

OUTLINE = [
    OutlineSection(section_id="summary", title="Executive summary", purpose="Answer the brief"),
    OutlineSection(section_id="findings", title="Findings", purpose="Evidence per question"),
    OutlineSection(section_id="limitations", title="Limitations", purpose="Gaps and unknowns"),
]


class PassThroughReviewer:
    """Ablation: sends every draft to human review without checking it."""

    def review(
        self,
        brief: Brief,
        plan: Plan,
        draft: WriterOutput,
        evidence: list[EvidenceView],
        *,
        review_round: int,
    ) -> AgentCall[ReviewerOutput]:
        output = ReviewerOutput(
            report_version=draft.report_version, review_round=review_round, outcome="pass"
        )
        return AgentCall(output, 0, generation={"provider": "none", "reason": "reviewer ablated"})


class SingleTaskPlanner:
    """Baseline: one fixed task covering every research question; no model call."""

    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]:
        task = PlanTask(
            task_id="all",
            question=("Answer every research question: " + " | ".join(brief.research_questions))[:500],
            tools=sorted(allowed_tools(brief)),
            expected_evidence="Sources for every research question",
            section_ids=["findings"],
        )
        plan = Plan(
            plan_version=version,
            tasks=[task],
            outline=OUTLINE,
            source_strategy="Baseline: search each research question once and collect the results.",
            assumptions=["Single-agent baseline (system B)"],
        )
        return AgentCall(plan, 0, generation={"provider": "none", "reason": "fixed baseline plan"})


class CollectOnlyResearcher:
    """Baseline: searches each research question and collects results, without a model."""

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        refs = []
        unresolved = []
        for question in brief.research_questions:
            hits = []
            if "web_search" in task.tools:
                hits += tools.search(question)[:3]
            if "search_uploads" in task.tools:
                hits += tools.search_uploads(question)[:2]
            found = [ref for hit in hits for ref in tools.collect(hit)]
            if not found:
                unresolved.append(question)
            refs += found
        unique = list({r.evidence_id: r for r in refs}.values())
        if not unique:
            output = ResearcherOutput(
                task_id=task.task_id, unresolved_questions=unresolved or [task.question]
            )
            return AgentCall(output, 0, generation={"provider": "none"})
        output = ResearcherOutput(
            task_id=task.task_id,
            evidence_ids=sorted(r.evidence_id for r in unique),
            findings=[
                ResearchFinding(
                    statement=f"Collected passage from {r.source_id}", evidence_ids=[r.evidence_id]
                )
                for r in unique
            ],
            unresolved_questions=unresolved,
        )
        return AgentCall(output, 0, generation={"provider": "none", "reason": "collection only"})


def model_fault_message(kind: str) -> str:
    return "model provider timed out" if kind == "timeout" else "model provider returned HTTP 500"


class FailingAgent:
    """Fixture `model_fault` in fake mode: every model-backed role fails like the provider."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def _fail(self) -> NoReturn:
        raise TransientError(model_fault_message(self.kind))

    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]:
        self._fail()

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        self._fail()

    def write(
        self,
        brief: Brief,
        plan: Plan,
        evidence: list[EvidenceView],
        *,
        report_version: int,
        findings: list[ReviewFinding],
    ) -> AgentCall[WriterOutput]:
        self._fail()

    def review(
        self,
        brief: Brief,
        plan: Plan,
        draft: WriterOutput,
        evidence: list[EvidenceView],
        *,
        review_round: int,
    ) -> AgentCall[ReviewerOutput]:
        self._fail()


class FailingLlm:
    """Fixture `model_fault` in LLM mode: every completion fails before reaching a provider."""

    name, model = "fault-fixture", "fault-fixture"

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = 0

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        self.calls += 1
        raise TransientError(model_fault_message(self.kind))


class FlakySearch:
    """Fixture `search_faults`: fails the first `times` searches with a transient HTTP status."""

    def __init__(self, inner: SearchProvider, status: int, times: int) -> None:
        self.inner, self.status, self.remaining = inner, status, times
        self.name = inner.name
        self.failures = 0

    def search(
        self, query: str, *, max_results: int, allowed_domains: list[str], blocked_domains: list[str]
    ) -> SearchResponse:
        if self.remaining > 0:
            self.remaining -= 1
            self.failures += 1
            raise TransientError(f"search provider returned HTTP {self.status}", retry_after=1.0)
        return self.inner.search(
            query, max_results=max_results, allowed_domains=allowed_domains, blocked_domains=blocked_domains
        )


class NoNetworkFetcher:
    """The offline corpus carries page text in search results, so evaluation never fetches.
    Any fetch attempt (for example a URL injected into a page) is refused and counted."""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.attempts.append(url)
        raise FetchError("network_disabled_in_evaluation")


AgentFactory = Callable[[Settings, RunContext, LlmProvider | None], AgentSuite]


def suite_factory(system: SystemId, mode: Mode, model_fault: str | None = None) -> AgentFactory:
    def build(settings: Settings, ctx: RunContext, llm: LlmProvider | None) -> AgentSuite:
        if mode == "fake":
            base = fake_agents()
        else:
            base = build_agents(settings.model_copy(update={"agent_mode": "llm"}), ctx, llm)
        if system == "C":
            base = replace(base, reviewer=PassThroughReviewer())
        elif system == "B":
            base = replace(
                base,
                planner=SingleTaskPlanner(),
                researcher=CollectOnlyResearcher(),
                reviewer=PassThroughReviewer(),
            )
        if mode == "fake" and model_fault:
            # Only the roles a model would perform fail; deterministic baseline parts do not.
            failing = FailingAgent(model_fault)
            if system == "B":
                return replace(base, writer=failing)
            return replace(base, planner=failing, researcher=failing, writer=failing)
        return base

    return build
