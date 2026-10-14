"""Human approval decisions bound to an exact artifact version and digest (FR-04)."""

from typing import Literal

from pydantic import Field

from app.contracts.common import Sha256Hex, ShortText, StrictModel, artifact_digest


class ApprovalDecision(StrictModel):
    artifact_kind: Literal["plan", "report"]
    artifact_version: int = Field(ge=1)
    artifact_digest: Sha256Hex
    decision: Literal["approve", "reject"]
    comment: ShortText | None = None


class StaleApproval(ValueError):
    pass


def check_decision_matches(decision: ApprovalDecision, current_version: int, current: object) -> None:
    """Reject decisions made against anything other than the exact current artifact.
    Permission checks happen separately, at decision time, in the API layer."""
    if decision.artifact_version != current_version:
        raise StaleApproval(
            f"decision targets version {decision.artifact_version}; current is {current_version}"
        )
    if decision.artifact_digest != artifact_digest(current):
        raise StaleApproval("decision digest does not match the current artifact")
