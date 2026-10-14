"""Researcher, writer, and reviewer output contracts (FR-06, FR-07)."""

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import Identifier, LongText, ShortText, StrictModel, find_duplicates


class ResearchFinding(StrictModel):
    statement: LongText
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=20)


class SourceConflict(StrictModel):
    description: ShortText
    evidence_ids: list[Identifier] = Field(min_length=2, max_length=20)


class ResearcherOutput(StrictModel):
    task_id: Identifier
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    findings: list[ResearchFinding] = Field(default_factory=list, max_length=50)
    unresolved_questions: list[ShortText] = Field(default_factory=list, max_length=20)
    conflicts: list[SourceConflict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _references_collected_evidence(self) -> "ResearcherOutput":
        collected = set(self.evidence_ids)
        cited = {e for f in self.findings for e in f.evidence_ids}
        cited |= {e for c in self.conflicts for e in c.evidence_ids}
        if unknown := sorted(cited - collected):
            raise ValueError(f"findings cite evidence not collected by this task: {unknown}")
        if not self.findings and not self.unresolved_questions:
            raise ValueError("no findings: report the question as unresolved instead")
        return self


ClaimKind = Literal["fact", "inference", "recommendation", "conflict", "unknown"]


class Claim(StrictModel):
    claim_id: Identifier
    kind: ClaimKind
    text: LongText
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _evidence_rules(self) -> "Claim":
        minimum = {"fact": 1, "inference": 1, "conflict": 2}.get(self.kind, 0)
        if len(self.evidence_ids) < minimum:
            raise ValueError(f"{self.kind} claims require at least {minimum} evidence_ids")
        if find_duplicates(list(self.evidence_ids)):
            raise ValueError("duplicate evidence_ids in claim")
        return self


class ReportSection(StrictModel):
    section_id: Identifier
    title: ShortText
    claims: list[Claim] = Field(min_length=1, max_length=100)


class WriterOutput(StrictModel):
    report_version: int = Field(ge=1)
    plan_version: int = Field(ge=1)
    sections: list[ReportSection] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_ids(self) -> "WriterOutput":
        if duplicates := find_duplicates([s.section_id for s in self.sections]):
            raise ValueError(f"duplicate section_id: {duplicates}")
        if duplicates := find_duplicates(self.claim_ids()):
            raise ValueError(f"duplicate claim_id: {duplicates}")
        return self

    def claim_ids(self) -> list[str]:
        return [c.claim_id for s in self.sections for c in s.claims]

    def cited_evidence_ids(self) -> set[str]:
        return {e for s in self.sections for c in s.claims for e in c.evidence_ids}


class CitationError(StrictModel):
    claim_id: Identifier
    evidence_id: str
    reason: Literal["unknown_or_unauthorized_evidence"]


def validate_citations(draft: WriterOutput, authorized_evidence_ids: set[str]) -> list[CitationError]:
    """Deterministic reference check: every cited ID must resolve to evidence authorized for
    this run. Passing this check does NOT show that a passage supports its claim; the
    reviewer and human sampling check support."""
    errors: list[CitationError] = []
    for section in draft.sections:
        for claim in section.claims:
            for evidence_id in claim.evidence_ids:
                if evidence_id not in authorized_evidence_ids:
                    errors.append(
                        CitationError(
                            claim_id=claim.claim_id,
                            evidence_id=evidence_id,
                            reason="unknown_or_unauthorized_evidence",
                        )
                    )
    return errors


class ReviewFinding(StrictModel):
    finding_id: Identifier
    severity: Literal["blocker", "major", "minor"]
    category: Literal[
        "unsupported_claim", "contradiction", "missing_section", "citation_error", "other"
    ]
    claim_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    requested_action: ShortText


ReviewOutcome = Literal["pass", "revise", "insufficient_evidence"]


class ReviewerOutput(StrictModel):
    report_version: int = Field(ge=1)
    review_round: int = Field(ge=1, le=2)
    outcome: ReviewOutcome
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _outcome_consistent(self) -> "ReviewerOutput":
        if duplicates := find_duplicates([f.finding_id for f in self.findings]):
            raise ValueError(f"duplicate finding_id: {duplicates}")
        severe = [f for f in self.findings if f.severity in ("blocker", "major")]
        if self.outcome == "pass" and severe:
            raise ValueError("pass is not allowed with blocker or major findings")
        if self.outcome != "pass" and not self.findings:
            raise ValueError(f"{self.outcome} requires at least one finding")
        return self

    def findings_by_severity(self) -> list[ReviewFinding]:
        order = {"blocker": 0, "major": 1, "minor": 2}
        return sorted(self.findings, key=lambda f: (order[f.severity], f.finding_id))
