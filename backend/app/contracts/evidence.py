"""Source and evidence provenance contracts (FR-05)."""

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, HttpUrl, StringConstraints, model_validator

from app.contracts.common import (
    Identifier,
    Sha256Hex,
    ShortText,
    StrictModel,
    sha256_hex,
)


class Source(StrictModel):
    source_id: Identifier
    kind: Literal["web", "upload"]
    url: HttpUrl | None = None
    upload_ref: Identifier | None = None
    title: ShortText | None = None
    retrieved_at: AwareDatetime
    published_on: date | None = None
    """Publication date stated by the source, if known. Distinct from retrieval time."""
    fetch_status: Literal["fetched", "failed"]
    failure_reason: ShortText | None = None
    content_sha256: Sha256Hex | None = None
    """Hash of the stored snapshot. Identifies content; does not prove it is true."""

    @model_validator(mode="after")
    def _consistent(self) -> Source:
        if self.kind == "web" and self.url is None:
            raise ValueError("web sources require url")
        if self.kind == "upload" and self.upload_ref is None:
            raise ValueError("upload sources require upload_ref")
        if self.fetch_status == "failed":
            if not self.failure_reason:
                raise ValueError("failed sources require failure_reason")
            if self.content_sha256 is not None:
                raise ValueError("failed sources cannot carry content")
        elif self.content_sha256 is None:
            raise ValueError("fetched sources require content_sha256")
        if self.published_on and self.published_on > self.retrieved_at.date():
            raise ValueError("published_on cannot be after retrieved_at")
        return self

    @property
    def citable(self) -> bool:
        """Failed fetches are recorded but are never presented as read sources."""
        return self.fetch_status == "fetched"


class EvidencePassage(StrictModel):
    evidence_id: Identifier
    source_id: Identifier
    task_id: Identifier
    locator: Annotated[str, StringConstraints(max_length=200)] | None = None
    """Page, section, or heading anchor, where available."""
    text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    text_sha256: Sha256Hex
    collected_at: AwareDatetime

    @model_validator(mode="after")
    def _hash_matches(self) -> EvidencePassage:
        if sha256_hex(self.text) != self.text_sha256:
            raise ValueError("text_sha256 does not match text")
        return self
