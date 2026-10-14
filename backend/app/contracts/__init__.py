"""Typed, schema-validated contracts shared by the API, workers, and agents.

These are contracts only: no persistence, no model calls. Policy checks that depend on
server configuration (tool allowlists, authorized evidence) are explicit functions so they
cannot be bypassed by model output.
"""

from app.contracts.agents import (
    Claim,
    CitationError,
    ReportSection,
    ResearcherOutput,
    ResearchFinding,
    ReviewerOutput,
    ReviewFinding,
    SourceConflict,
    WriterOutput,
    validate_citations,
)
from app.contracts.approval import ApprovalDecision, StaleApproval, check_decision_matches
from app.contracts.brief import Brief, Budget, RunLimits, SourcePolicy
from app.contracts.common import artifact_digest, canonical_json
from app.contracts.evaluation import EvalCase, EvalExpectation
from app.contracts.evidence import EvidencePassage, Source
from app.contracts.plan import (
    OutlineSection,
    Plan,
    PlanPolicy,
    PlanPolicyViolation,
    PlanTask,
    enforce_plan_policy,
)
from app.contracts.run_state import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    WAITING_STATES,
    InvalidTransition,
    RunState,
    check_transition,
    route_after_review,
)

# Contracts exported as JSON Schema to docs/contracts/.
SCHEMA_MODELS = {
    "brief": Brief,
    "plan": Plan,
    "source": Source,
    "evidence-passage": EvidencePassage,
    "researcher-output": ResearcherOutput,
    "writer-output": WriterOutput,
    "reviewer-output": ReviewerOutput,
    "approval-decision": ApprovalDecision,
    "eval-case": EvalCase,
}

__all__ = [
    "ALLOWED_TRANSITIONS",
    "SCHEMA_MODELS",
    "TERMINAL_STATES",
    "WAITING_STATES",
    "ApprovalDecision",
    "Brief",
    "Budget",
    "CitationError",
    "Claim",
    "EvalCase",
    "EvalExpectation",
    "EvidencePassage",
    "InvalidTransition",
    "OutlineSection",
    "Plan",
    "PlanPolicy",
    "PlanPolicyViolation",
    "PlanTask",
    "ReportSection",
    "ResearchFinding",
    "ResearcherOutput",
    "ReviewFinding",
    "ReviewerOutput",
    "RunLimits",
    "RunState",
    "Source",
    "SourceConflict",
    "SourcePolicy",
    "StaleApproval",
    "WriterOutput",
    "artifact_digest",
    "canonical_json",
    "check_decision_matches",
    "check_transition",
    "enforce_plan_policy",
    "route_after_review",
    "validate_citations",
]
