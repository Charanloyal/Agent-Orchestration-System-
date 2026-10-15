"""LLM-backed writer and reviewer (FR-06, FR-07)."""

import json
from typing import Any

from app.agents.base import AgentCall, EvidenceRef, EvidenceView
from app.agents.llm_researcher import format_passages
from app.agents.prompts import (
    REVIEWER_SYSTEM,
    REVIEWER_USER,
    REVIEWER_VERSION,
    WRITER_SYSTEM,
    WRITER_USER,
    WRITER_VERSION,
)
from app.agents.review_checks import deterministic_findings
from app.agents.structured import StructuredCall, call_structured, schema_for
from app.contracts import (
    Brief,
    Plan,
    ReviewerOutput,
    ReviewFinding,
    WriterOutput,
    validate_citations,
)
from app.providers.llm import LlmProvider

MAX_WRITER_PASSAGES = 24
PASSAGE_CHARS = 900


def _generation(llm: LlmProvider, prompt_version: str, call: StructuredCall[Any]) -> dict[str, Any]:
    return {
        "provider": llm.name,
        "model": llm.model,
        "prompt_version": prompt_version,
        "attempts": call.attempts,
        "input_tokens": sum(u.input_tokens for u in call.usage),
        "output_tokens": sum(u.output_tokens for u in call.usage),
    }


def select_passages(
    plan: Plan, evidence: list[EvidenceView], limit: int = MAX_WRITER_PASSAGES
) -> list[EvidenceView]:
    """Round-robin across tasks so every planned question is represented within the limit."""
    by_task: dict[str, list[EvidenceView]] = {}
    for item in evidence:
        by_task.setdefault(item.task_id, []).append(item)
    order = [t.task_id for t in plan.tasks] + sorted(set(by_task) - {t.task_id for t in plan.tasks})
    selected: list[EvidenceView] = []
    depth = 0
    while len(selected) < limit and any(len(by_task.get(t, [])) > depth for t in order):
        for task_id in order:
            items = by_task.get(task_id, [])
            if depth < len(items) and len(selected) < limit:
                selected.append(items[depth])
        depth += 1
    return selected


def _refs(items: list[EvidenceView]) -> tuple[list[EvidenceRef], dict[str, str]]:
    refs = [EvidenceRef(e.evidence_id, e.source_id, e.text[:PASSAGE_CHARS]) for e in items]
    titles = {e.source_id: (e.title or e.source_id) for e in items}
    return refs, titles


class LlmWriter:
    def __init__(self, llm: LlmProvider, *, max_output_tokens: int = 2500) -> None:
        self.llm = llm
        self.max_output_tokens = max_output_tokens

    def write(
        self,
        brief: Brief,
        plan: Plan,
        evidence: list[EvidenceView],
        *,
        report_version: int,
        findings: list[ReviewFinding],
    ) -> AgentCall[WriterOutput]:
        selected = select_passages(plan, evidence)
        refs, titles = _refs(selected)
        allowed = {e.evidence_id for e in selected}
        outline_ids = {s.section_id for s in plan.outline}
        findings_block = ""
        if findings:
            findings_block = (
                "Review findings to fix:\n"
                + "\n".join(
                    f"- [{f.severity}] {f.category} on claims {', '.join(f.claim_ids) or '-'}: "
                    f"{f.requested_action}"
                    for f in findings
                )
                + "\n"
            )

        def server_checks(draft: WriterOutput) -> None:
            if errors := validate_citations(draft, allowed):
                unknown_ids = sorted({e.evidence_id for e in errors})[:5]
                raise ValueError(f"evidence_ids not among the provided passages: {unknown_ids}")
            if unknown := sorted({s.section_id for s in draft.sections} - outline_ids):
                raise ValueError(f"section_ids not in the outline: {unknown}")

        call = call_structured(
            self.llm,
            WriterOutput,
            step="writer",
            system=WRITER_SYSTEM,
            user=WRITER_USER.format(
                topic=brief.topic,
                audience=brief.audience,
                questions="\n".join(f"- {q}" for q in brief.research_questions),
                outline="\n".join(f"- {s.section_id}: {s.title} — {s.purpose}" for s in plan.outline),
                version=report_version,
                plan_version=plan.plan_version,
                findings_block=findings_block,
                passages=format_passages(refs, titles) if refs else "(no evidence was collected)",
                schema=schema_for(WriterOutput),
            ),
            max_output_tokens=self.max_output_tokens,
            validate=server_checks,
        )
        return AgentCall(
            call.output,
            call.attempts,
            generation=_generation(self.llm, WRITER_VERSION, call),
            usage=tuple(call.usage),
        )


class LlmReviewer:
    """Model review merged with the deterministic checks (which always run)."""

    def __init__(self, llm: LlmProvider, *, max_output_tokens: int = 1500) -> None:
        self.llm = llm
        self.max_output_tokens = max_output_tokens

    def review(
        self,
        brief: Brief,
        plan: Plan,
        draft: WriterOutput,
        evidence: list[EvidenceView],
        *,
        review_round: int,
    ) -> AgentCall[ReviewerOutput]:
        by_id = {e.evidence_id: e for e in evidence}
        claim_ids = set(draft.claim_ids())
        blocks = []
        for section in draft.sections:
            for claim in section.claims:
                cited = [e for e in claim.evidence_ids if e in by_id]
                refs, titles = _refs([by_id[e] for e in cited])
                passages = format_passages(refs, titles) if refs else "(no passages cited)"
                blocks.append(
                    f"[{claim.claim_id}] ({claim.kind}, section {section.section_id}) "
                    f"{claim.text}\n{passages}"
                )

        def server_checks(review: ReviewerOutput) -> None:
            for finding in review.findings:
                if unknown := sorted(set(finding.claim_ids) - claim_ids):
                    raise ValueError(f"finding {finding.finding_id} references unknown claims {unknown[:5]}")
                if unknown := sorted(set(finding.evidence_ids) - set(by_id)):
                    raise ValueError(
                        f"finding {finding.finding_id} references unknown evidence {unknown[:5]}"
                    )

        call = call_structured(
            self.llm,
            ReviewerOutput,
            step="reviewer",
            system=REVIEWER_SYSTEM,
            user=REVIEWER_USER.format(
                questions="\n".join(f"- {q}" for q in brief.research_questions),
                review_round=review_round,
                report_version=draft.report_version,
                claims="\n\n".join(blocks),
                schema=schema_for(ReviewerOutput),
            ),
            max_output_tokens=self.max_output_tokens,
            validate=server_checks,
        )
        merged = merge_reviews(call.output, deterministic_findings(draft, by_id))
        return AgentCall(
            merged,
            call.attempts,
            generation=_generation(self.llm, REVIEWER_VERSION, call),
            usage=tuple(call.usage),
        )


def merge_reviews(model: ReviewerOutput, deterministic: list[ReviewFinding]) -> ReviewerOutput:
    """Deterministic findings can only make the outcome stricter, never more lenient.
    Model finding ids get an indexed 'm' prefix so they never collide with 'd-' ids."""
    findings = [
        f.model_copy(update={"finding_id": f"m{i}-{f.finding_id}"[:64]})
        for i, f in enumerate(model.findings, 1)
    ]
    order = {"blocker": 0, "major": 1, "minor": 2}
    merged = sorted([*deterministic, *findings], key=lambda f: order[f.severity])[:50]
    outcome = model.outcome
    if outcome == "pass" and any(f.severity in ("blocker", "major") for f in merged):
        outcome = "revise"
    return ReviewerOutput.model_validate(
        {
            **json.loads(model.model_dump_json()),
            "outcome": outcome,
            "findings": [f.model_dump(mode="json") for f in merged],
        }
    )
