"""Evaluation case wrapper for development and held-out briefs (PRD §4.1)."""

from typing import Literal

from pydantic import Field

from app.contracts.brief import Brief
from app.contracts.common import Identifier, ShortText, StrictModel

EvalCategory = Literal[
    "answerable",
    "conflicting_evidence",
    "unavailable_evidence",
    "stale_sources",
    "malicious_content",
    "provider_failure",
]

ExpectedOutcome = Literal["reviewable_draft", "needs_attention_with_explanation", "failed_safely"]


class EvalExpectation(StrictModel):
    outcome: ExpectedOutcome
    must_cover: list[ShortText] = Field(default_factory=list, max_length=10)
    """Points a human scorer checks for coverage. Not gold answers."""
    must_not: list[ShortText] = Field(default_factory=list, max_length=10)
    """Behaviors that fail the case outright (e.g. fabricated pricing, following injected text)."""
    fixture_notes: ShortText | None = None
    """How fake providers should behave for this case (injected failure, conflicting pages)."""


class EvalCase(StrictModel):
    case_id: Identifier
    split: Literal["dev", "heldout"]
    category: EvalCategory
    brief: Brief
    expected: EvalExpectation
