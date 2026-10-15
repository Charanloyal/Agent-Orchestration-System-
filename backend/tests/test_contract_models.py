from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts import (
    ApprovalDecision,
    Brief,
    EvidencePassage,
    ResearcherOutput,
    ReviewerOutput,
    Source,
    StaleApproval,
    WriterOutput,
    artifact_digest,
    check_decision_matches,
    validate_citations,
)
from app.contracts.common import sha256_hex

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def brief_data(**overrides: object) -> dict:
    data: dict = {
        "topic": "Compare document search tools for a small team",
        "audience": "Engineering manager",
        "research_questions": ["Which tools support SSO?", "What is public pricing?"],
        "source_policy": {"allowed_source_types": ["vendor_docs", "public_web"]},
        "budget": {"max_estimated_cost": "2.50"},
    }
    data.update(overrides)
    return data


class TestBrief:
    def test_valid_with_default_limits(self) -> None:
        brief = Brief.model_validate(brief_data())
        assert brief.limits.max_review_rounds == 2

    @pytest.mark.parametrize(
        "limits",
        [
            {"max_review_rounds": 3},
            {"max_parallel_tasks": 0},
            {"deadline_minutes": 10_000},
        ],
    )
    def test_rejects_invalid_limits(self, limits: dict) -> None:
        with pytest.raises(ValidationError):
            Brief.model_validate(brief_data(limits=limits))

    @pytest.mark.parametrize("amount", ["0", "-1", "50.01", "1.234"])
    def test_rejects_invalid_budget(self, amount: str) -> None:
        with pytest.raises(ValidationError):
            Brief.model_validate(brief_data(budget={"max_estimated_cost": amount}))

    def test_rejects_duplicate_questions_case_insensitively(self) -> None:
        with pytest.raises(ValidationError, match="duplicate research questions"):
            Brief.model_validate(brief_data(research_questions=["Price?", "price?"]))

    @pytest.mark.parametrize("domain", ["http://example.com", "localhost", "10.0.0.1", "a b.com"])
    def test_rejects_non_hostname_domains(self, domain: str) -> None:
        policy = {"allowed_source_types": ["public_web"], "allowed_domains": [domain]}
        with pytest.raises(ValidationError):
            Brief.model_validate(brief_data(source_policy=policy))

    def test_rejects_domain_both_allowed_and_blocked(self) -> None:
        policy = {
            "allowed_source_types": ["public_web"],
            "allowed_domains": ["Example.com"],
            "blocked_domains": ["example.com"],
        }
        with pytest.raises(ValidationError, match="both allowed and blocked"):
            Brief.model_validate(brief_data(source_policy=policy))


class TestEvidence:
    def test_failed_fetch_is_recorded_but_not_citable(self) -> None:
        source = Source(
            source_id="s1",
            kind="web",
            url="https://example.com/pricing",
            retrieved_at=NOW,
            fetch_status="failed",
            failure_reason="HTTP 403",
        )
        assert not source.citable

    def test_failed_fetch_cannot_carry_content(self) -> None:
        with pytest.raises(ValidationError, match="cannot carry content"):
            Source(
                source_id="s1",
                kind="web",
                url="https://example.com",
                retrieved_at=NOW,
                fetch_status="failed",
                failure_reason="timeout",
                content_sha256="0" * 64,
            )

    def test_publication_after_retrieval_rejected(self) -> None:
        with pytest.raises(ValidationError, match="published_on"):
            Source(
                source_id="s1",
                kind="web",
                url="https://example.com",
                retrieved_at=NOW,
                published_on="2027-01-01",
                fetch_status="fetched",
                content_sha256="0" * 64,
            )

    def test_requires_timezone_aware_retrieval_time(self) -> None:
        with pytest.raises(ValidationError):
            Source(
                source_id="s1",
                kind="upload",
                upload_ref="u1",
                retrieved_at=datetime(2026, 1, 1),
                fetch_status="fetched",
                content_sha256="0" * 64,
            )

    def test_passage_hash_must_match_text(self) -> None:
        text = "Plan B costs $10 per user per month."
        EvidencePassage(
            evidence_id="e1",
            source_id="s1",
            task_id="t1",
            text=text,
            text_sha256=sha256_hex(text),
            collected_at=NOW,
        )
        with pytest.raises(ValidationError, match="does not match"):
            EvidencePassage(
                evidence_id="e1",
                source_id="s1",
                task_id="t1",
                text=text + " (edited)",
                text_sha256=sha256_hex(text),
                collected_at=NOW,
            )


class TestAgentOutputs:
    def test_researcher_cannot_cite_uncollected_evidence(self) -> None:
        with pytest.raises(ValidationError, match="not collected"):
            ResearcherOutput(
                task_id="t1",
                evidence_ids=["e1"],
                findings=[{"statement": "A costs $5.", "evidence_ids": ["e2"]}],
            )

    def test_researcher_with_nothing_found_must_say_so(self) -> None:
        with pytest.raises(ValidationError, match="unresolved"):
            ResearcherOutput(task_id="t1")
        ResearcherOutput(task_id="t1", unresolved_questions=["No public pricing found."])

    @pytest.mark.parametrize(
        ("kind", "evidence", "ok"),
        [
            ("fact", [], False),
            ("fact", ["e1"], True),
            ("inference", [], False),
            ("conflict", ["e1"], False),
            ("conflict", ["e1", "e2"], True),
            ("recommendation", [], True),
            ("unknown", [], True),
        ],
    )
    def test_claim_evidence_rules(self, kind: str, evidence: list[str], ok: bool) -> None:
        data = {
            "report_version": 1,
            "plan_version": 1,
            "sections": [
                {
                    "section_id": "s",
                    "title": "S",
                    "claims": [
                        {
                            "claim_id": "c1",
                            "kind": kind,
                            "text": "x",
                            "evidence_ids": evidence,
                        }
                    ],
                }
            ],
        }
        if ok:
            WriterOutput.model_validate(data)
        else:
            with pytest.raises(ValidationError):
                WriterOutput.model_validate(data)

    def test_citation_validation_flags_unauthorized_ids(self) -> None:
        draft = WriterOutput.model_validate(
            {
                "report_version": 1,
                "plan_version": 1,
                "sections": [
                    {
                        "section_id": "s",
                        "title": "S",
                        "claims": [
                            {
                                "claim_id": "c1",
                                "kind": "fact",
                                "text": "x",
                                "evidence_ids": ["e1"],
                            },
                            {
                                "claim_id": "c2",
                                "kind": "fact",
                                "text": "y",
                                "evidence_ids": ["e9"],
                            },
                        ],
                    }
                ],
            }
        )
        errors = validate_citations(draft, authorized_evidence_ids={"e1"})
        assert [(e.claim_id, e.evidence_id) for e in errors] == [("c2", "e9")]

    def test_reviewer_cannot_pass_with_blocker(self) -> None:
        finding = {
            "finding_id": "f1",
            "severity": "blocker",
            "category": "unsupported_claim",
            "claim_ids": ["c1"],
            "requested_action": "Remove or cite",
        }
        with pytest.raises(ValidationError, match="pass is not allowed"):
            ReviewerOutput(report_version=1, review_round=1, outcome="pass", findings=[finding])
        ReviewerOutput(report_version=1, review_round=1, outcome="revise", findings=[finding])

    def test_reviewer_round_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            ReviewerOutput(report_version=1, review_round=3, outcome="pass")


class TestApproval:
    def test_decision_must_match_version_and_digest(self) -> None:
        artifact = {"plan_version": 2, "tasks": ["t1"]}
        good = ApprovalDecision(
            artifact_kind="plan",
            artifact_version=2,
            artifact_digest=artifact_digest(artifact),
            decision="approve",
        )
        check_decision_matches(good, 2, artifact)

        with pytest.raises(StaleApproval, match="version"):
            check_decision_matches(good, 3, artifact)
        with pytest.raises(StaleApproval, match="digest"):
            check_decision_matches(good, 2, {**artifact, "tasks": ["t1", "t2"]})
