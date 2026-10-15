"""Deterministic claim-support checks (FR-07). They run on every draft, in fake and LLM mode,
before and alongside the model reviewer: cheap, explainable, and impossible to talk out of.

- Numeric fidelity: every number stated in a fact must literally appear in a cited passage.
- Lexical support: a fact must share meaningful words with its cited passages.
These catch fabricated figures and obviously mis-cited claims; semantic support beyond that
is the model reviewer's and the human reviewer's job.
"""

import re

from app.agents.base import EvidenceView
from app.contracts import ReviewFinding, WriterOutput

_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[a-z][a-z0-9-]{3,}")
_STOP = frozenset(
    [
        "about",
        "above",
        "after",
        "again",
        "also",
        "among",
        "another",
        "based",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "could",
        "does",
        "each",
        "from",
        "have",
        "into",
        "more",
        "most",
        "other",
        "over",
        "same",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "within",
        "would",
        "your",
        "documents",
        "point",
        "source",
        "sources",
    ]
)
MIN_CONTENT_WORDS = 4
MIN_OVERLAP = 0.2


def numbers(text: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in _NUMBER.findall(text)}


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def deterministic_findings(draft: WriterOutput, evidence: dict[str, EvidenceView]) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for section in draft.sections:
        for claim in section.claims:
            if claim.kind not in ("fact", "inference"):
                continue
            # Claims may name their source, so titles count as cited text.
            cited = " ".join(
                f"{evidence[e].title or ''} {evidence[e].text}" for e in claim.evidence_ids if e in evidence
            )
            missing_numbers = sorted(numbers(claim.text) - numbers(cited))
            if missing_numbers and claim.kind == "fact":
                findings.append(
                    ReviewFinding(
                        finding_id=f"d-num-{claim.claim_id}"[:64],
                        severity="blocker",
                        category="unsupported_claim",
                        claim_ids=[claim.claim_id],
                        evidence_ids=list(claim.evidence_ids),
                        requested_action=(
                            f"The figure(s) {', '.join(missing_numbers[:5])} in claim {claim.claim_id} "
                            "do not appear in its cited passages. Cite a passage that states them or "
                            "remove them."
                        )[:500],
                    )
                )
                continue
            words = content_words(claim.text)
            if claim.kind == "fact" and len(words) >= MIN_CONTENT_WORDS:
                overlap = len(words & content_words(cited)) / len(words)
                if overlap < MIN_OVERLAP:
                    findings.append(
                        ReviewFinding(
                            finding_id=f"d-sup-{claim.claim_id}"[:64],
                            severity="major",
                            category="unsupported_claim",
                            claim_ids=[claim.claim_id],
                            evidence_ids=list(claim.evidence_ids),
                            requested_action=(
                                f"Claim {claim.claim_id} shares little with its cited passages; "
                                "verify support, re-cite, or restate it as an inference or unknown."
                            ),
                        )
                    )
    return findings
