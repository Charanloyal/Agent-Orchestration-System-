"""Keep a live run going when the model fails permanently (ADR 0030).

Each language-model agent is wrapped. If the model rejects a request or keeps returning
invalid output (StepFailed), that one step is done by the deterministic agent instead. The
artifact's provenance records `fallback_reason` and `fallback_from`, so the timeline and the
artifact itself say which step was not written by the model. Transient errors (timeouts,
rate limits) are not caught here: the worker retries them first.
"""

import logging
from collections.abc import Callable
from dataclasses import replace

from app.agents.base import AgentCall, AgentSuite, EvidenceView, ResearchTools
from app.contracts import Brief, Plan, PlanTask, ResearcherOutput, ReviewerOutput, ReviewFinding, WriterOutput
from app.workflow.errors import StepFailed

log = logging.getLogger("aos.agents")


def _fallback[T](
    live: Callable[[], AgentCall[T]], fake: Callable[[], AgentCall[T]], source: str
) -> AgentCall[T]:
    try:
        return live()
    except StepFailed as exc:
        reason = exc.reason[:300]
        log.warning(
            "model step fell back to the deterministic agent", extra={"step": exc.step, "reason": reason}
        )
        call = fake()
        return replace(
            call,
            generation={
                **call.generation,
                "provider": "fake",
                "fallback_reason": reason,
                "fallback_from": source,
            },
        )


class FallbackPlanner:
    def __init__(self, live: object, fake: object, source: str) -> None:
        self.live, self.fake, self.source = live, fake, source

    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]:
        return _fallback(
            lambda: self.live.plan(brief, version=version, feedback=feedback),  # type: ignore[attr-defined]
            lambda: self.fake.plan(brief, version=version, feedback=feedback),  # type: ignore[attr-defined]
            self.source,
        )


class FallbackResearcher:
    def __init__(self, live: object, fake: object, source: str) -> None:
        self.live, self.fake, self.source = live, fake, source

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        return _fallback(
            lambda: self.live.research(brief, task, tools),  # type: ignore[attr-defined]
            lambda: self.fake.research(brief, task, tools),  # type: ignore[attr-defined]
            self.source,
        )


class FallbackWriter:
    def __init__(self, live: object, fake: object, source: str) -> None:
        self.live, self.fake, self.source = live, fake, source

    def write(
        self,
        brief: Brief,
        plan: Plan,
        evidence: list[EvidenceView],
        *,
        report_version: int,
        findings: list[ReviewFinding],
    ) -> AgentCall[WriterOutput]:
        return _fallback(
            lambda: self.live.write(brief, plan, evidence, report_version=report_version, findings=findings),  # type: ignore[attr-defined]
            lambda: self.fake.write(brief, plan, evidence, report_version=report_version, findings=findings),  # type: ignore[attr-defined]
            self.source,
        )


class FallbackReviewer:
    def __init__(self, live: object, fake: object, source: str) -> None:
        self.live, self.fake, self.source = live, fake, source

    def review(
        self,
        brief: Brief,
        plan: Plan,
        draft: WriterOutput,
        evidence: list[EvidenceView],
        *,
        review_round: int,
    ) -> AgentCall[ReviewerOutput]:
        return _fallback(
            lambda: self.live.review(brief, plan, draft, evidence, review_round=review_round),  # type: ignore[attr-defined]
            lambda: self.fake.review(brief, plan, draft, evidence, review_round=review_round),  # type: ignore[attr-defined]
            self.source,
        )


def with_fallback(live: AgentSuite, fake: AgentSuite, source: str) -> AgentSuite:
    return AgentSuite(
        planner=FallbackPlanner(live.planner, fake.planner, source),
        researcher=FallbackResearcher(live.researcher, fake.researcher, source),
        writer=FallbackWriter(live.writer, fake.writer, source),
        reviewer=FallbackReviewer(live.reviewer, fake.reviewer, source),
    )
