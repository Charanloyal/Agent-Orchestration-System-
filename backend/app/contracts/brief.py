"""Research brief contract (FR-02)."""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.contracts.common import ShortText, StrictModel, find_duplicates

SourceType = Literal["public_web", "vendor_docs", "uploaded_documents"]

_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

Domain = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=253)]


class SourcePolicy(StrictModel):
    allowed_source_types: list[SourceType] = Field(min_length=1, max_length=3)
    allowed_domains: list[Domain] = Field(default_factory=list, max_length=50)
    """Empty means "any public domain the search provider returns", still subject to SSRF rules."""
    blocked_domains: list[Domain] = Field(default_factory=list, max_length=50)
    date_cutoff: date | None = None
    """Ignore sources published before this date, when the publication date is known."""

    @field_validator("allowed_domains", "blocked_domains")
    @classmethod
    def _valid_hostnames(cls, domains: list[str]) -> list[str]:
        for domain in domains:
            if not _HOSTNAME.match(domain):
                raise ValueError(f"not a valid hostname: {domain!r}")
        if duplicates := find_duplicates(domains):
            raise ValueError(f"duplicate domains: {duplicates}")
        return domains

    @model_validator(mode="after")
    def _consistent(self) -> "SourcePolicy":
        if overlap := set(self.allowed_domains) & set(self.blocked_domains):
            raise ValueError(f"domains both allowed and blocked: {sorted(overlap)}")
        if find_duplicates(list(self.allowed_source_types)):
            raise ValueError("duplicate source types")
        return self


class Budget(StrictModel):
    currency: Literal["USD"] = "USD"
    max_estimated_cost: Decimal = Field(gt=0, le=Decimal("50"), decimal_places=2)
    """Ceiling for *estimated* spend, enforced by reservations. Not a provider billing cap."""


class RunLimits(StrictModel):
    """User-requested limits. The server clamps them to workspace policy; it never raises them."""

    max_tasks: int = Field(default=6, ge=1, le=12)
    max_parallel_tasks: int = Field(default=2, ge=1, le=4)
    max_tool_calls: int = Field(default=60, ge=1, le=200)
    max_review_rounds: int = Field(default=2, ge=1, le=2)
    deadline_minutes: int = Field(default=60, ge=5, le=720)


class Brief(StrictModel):
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]
    audience: ShortText
    research_questions: list[ShortText] = Field(min_length=1, max_length=10)
    source_policy: SourcePolicy
    output_format: Literal["markdown"] = "markdown"
    budget: Budget
    limits: RunLimits = Field(default_factory=RunLimits)

    @field_validator("research_questions")
    @classmethod
    def _unique_questions(cls, questions: list[str]) -> list[str]:
        if duplicates := find_duplicates([q.casefold() for q in questions]):
            raise ValueError(f"duplicate research questions: {duplicates}")
        return questions
