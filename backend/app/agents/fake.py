"""Deterministic fake agents for tests, CI, and demos without a model provider."""

from app.agents.base import AgentCall, AgentSuite, EvidenceView, ResearchTools
from app.agents.review_checks import deterministic_findings
from app.contracts import (
    Brief,
    Claim,
    OutlineSection,
    Plan,
    PlanTask,
    ReportSection,
    ResearcherOutput,
    ResearchFinding,
    ReviewerOutput,
    ReviewFinding,
    WriterOutput,
)
from app.policy.tools import allowed_tools


class FakePlanner:
    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]:
        questions = brief.research_questions[: max(1, brief.limits.max_tasks - 1)]
        tools = sorted(allowed_tools(brief))
        tasks = [
            PlanTask(
                task_id=f"t{i}",
                question=question,
                tools=tools,
                expected_evidence="Primary documentation or reputable public sources",
                section_ids=["findings"],
            )
            for i, question in enumerate(questions, 1)
        ]
        if len(tasks) > 1 and len(tasks) < brief.limits.max_tasks:
            tasks.append(
                PlanTask(
                    task_id="synthesis",
                    question=f"How do the findings compare for: {brief.topic}"[:500],
                    depends_on=[t.task_id for t in tasks],
                    tools=tools,
                    expected_evidence="Comparative sources",
                    section_ids=["summary"],
                )
            )
        assumptions = [f"Plan revision {version}"]
        if feedback:
            assumptions.append(f"Revised after reviewer feedback: {feedback}"[:500])
        plan = Plan(
            plan_version=version,
            tasks=tasks,
            outline=[
                OutlineSection(section_id="summary", title="Executive summary", purpose="Answer the brief"),
                OutlineSection(section_id="findings", title="Findings", purpose="Evidence per question"),
                OutlineSection(section_id="limitations", title="Limitations", purpose="Gaps and unknowns"),
            ],
            source_strategy="Fake provider: deterministic synthetic passages only.",
            assumptions=assumptions,
        )
        return AgentCall(plan, 1)


class FakeResearcher:
    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        hits = []
        if "web_search" in task.tools:
            hits += tools.search(task.question)[:3]
        if "search_uploads" in task.tools:
            hits += tools.search_uploads(task.question)[:2]
        refs = [ref for hit in hits for ref in tools.collect(hit)]
        if not refs:
            return AgentCall(ResearcherOutput(task_id=task.task_id, unresolved_questions=[task.question]), 1)
        findings = [
            ResearchFinding(
                statement=f"Source {ref.source_id} addresses: {task.question}"[:4000],
                evidence_ids=[ref.evidence_id],
            )
            for ref in refs
        ]
        return AgentCall(
            ResearcherOutput(
                task_id=task.task_id, evidence_ids=sorted({r.evidence_id for r in refs}), findings=findings
            ),
            1,
        )


DEMO_UNSUPPORTED_MARKER = "(demo: unsupported claim)"


def first_sentence(text: str, limit: int = 240) -> str:
    sentence = text.strip().split("\n")[0]
    for stop in (". ", "? ", "! "):
        if stop in sentence:
            sentence = sentence[: sentence.index(stop) + 1]
            break
    return sentence[:limit].strip()


class FakeWriter:
    """Deterministic writer: quotes the first sentence of the best passage per task, so every
    fact is literally supported. Revisions drop claims the reviewer flagged as blocker/major.
    Briefs whose topic contains DEMO_UNSUPPORTED_MARKER get one fabricated figure in the first
    version, to demonstrate the reviewer catching it (demo/testing aid only)."""

    def write(
        self,
        brief: Brief,
        plan: Plan,
        evidence: list[EvidenceView],
        *,
        report_version: int,
        findings: list[ReviewFinding],
    ) -> AgentCall[WriterOutput]:
        flagged = {c for f in findings if f.severity in ("blocker", "major") for c in f.claim_ids}
        by_task: dict[str, list[EvidenceView]] = {}
        for item in evidence:
            by_task.setdefault(item.task_id, []).append(item)
        finding_claims: list[Claim] = []
        for i, item in enumerate((e for t in plan.tasks for e in by_task.get(t.task_id, [])[:1]), 1):
            claim_id = f"f{i}"
            if claim_id in flagged:
                continue
            finding_claims.append(
                Claim(
                    claim_id=claim_id,
                    kind="fact",
                    text=f'{(item.title or item.source_id)[:120]}: "{first_sentence(item.text)}"',
                    evidence_ids=[item.evidence_id],
                )
            )
        if (
            DEMO_UNSUPPORTED_MARKER in brief.topic
            and report_version == 1
            and finding_claims
            and "planted" not in flagged
        ):
            finding_claims.append(
                Claim(
                    claim_id="planted",
                    kind="fact",
                    text="The leading option costs 37 dollars per seat and serves 12000 customers.",
                    evidence_ids=[finding_claims[0].evidence_ids[0]],
                )
            )
        summary = [
            Claim(
                claim_id="s1",
                kind="recommendation",
                text=f"Review the cited sources before deciding on: {brief.topic}"[:4000],
            )
        ]
        if finding_claims:
            summary.insert(
                0,
                Claim(
                    claim_id="s0",
                    kind="inference",
                    text="The collected sources address the planned questions.",
                    evidence_ids=[finding_claims[0].evidence_ids[0]],
                ),
            )
        limitations = [
            Claim(
                claim_id="l1",
                kind="unknown",
                text="Generated by deterministic fake agents; quotes sources without analysis.",
            )
        ]
        if flagged:
            limitations.append(
                Claim(
                    claim_id="l2",
                    kind="unknown",
                    text=f"Removed {len(flagged)} claim(s) the reviewer found unsupported.",
                )
            )
        sections = [ReportSection(section_id="summary", title="Executive summary", claims=summary)]
        if finding_claims:
            sections.append(ReportSection(section_id="findings", title="Findings", claims=finding_claims))
        sections.append(ReportSection(section_id="limitations", title="Limitations", claims=limitations))
        return AgentCall(
            WriterOutput(report_version=report_version, plan_version=plan.plan_version, sections=sections), 1
        )


class FakeReviewer:
    """Deterministic reviewer: the code-level support checks only."""

    def review(
        self,
        brief: Brief,
        plan: Plan,
        draft: WriterOutput,
        evidence: list[EvidenceView],
        *,
        review_round: int,
    ) -> AgentCall[ReviewerOutput]:
        findings = deterministic_findings(draft, {e.evidence_id: e for e in evidence})
        outcome = "revise" if any(f.severity in ("blocker", "major") for f in findings) else "pass"
        return AgentCall(
            ReviewerOutput(
                report_version=draft.report_version,
                review_round=review_round,
                outcome=outcome,
                findings=findings,
            ),
            1,
        )


def fake_agents() -> AgentSuite:
    return AgentSuite(FakePlanner(), FakeResearcher(), FakeWriter(), FakeReviewer())
