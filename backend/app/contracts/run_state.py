"""Run state machine (PRD §3.5) and bounded review routing (PRD §3.3)."""

from enum import StrEnum

from app.contracts.agents import ReviewOutcome

MAX_REVIEW_ROUNDS = 2


class RunState(StrEnum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"
    RESEARCHING = "RESEARCHING"
    WRITING = "WRITING"
    REVIEWING = "REVIEWING"
    AWAITING_REPORT_APPROVAL = "AWAITING_REPORT_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


S = RunState

TERMINAL_STATES = frozenset({S.SUCCEEDED, S.NEEDS_ATTENTION, S.FAILED, S.CANCELLED, S.EXPIRED})

# States in which no worker holds a lease. Waiting for a human must not occupy a worker.
WAITING_STATES = frozenset({S.AWAITING_PLAN_APPROVAL, S.AWAITING_REPORT_APPROVAL})

_ACTIVE = (S.PLANNING, S.RESEARCHING, S.WRITING, S.REVIEWING)

ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    S.QUEUED: frozenset({S.PLANNING, S.CANCELLED, S.FAILED, S.EXPIRED}),
    S.PLANNING: frozenset({S.AWAITING_PLAN_APPROVAL, S.NEEDS_ATTENTION, S.FAILED}),
    S.AWAITING_PLAN_APPROVAL: frozenset(
        # Approve -> research; reject -> planner proposes a new plan version.
        {S.RESEARCHING, S.PLANNING, S.CANCELLED, S.EXPIRED}
    ),
    S.RESEARCHING: frozenset({S.WRITING, S.NEEDS_ATTENTION, S.FAILED}),
    S.WRITING: frozenset({S.REVIEWING, S.NEEDS_ATTENTION, S.FAILED}),
    S.REVIEWING: frozenset(
        {
            S.AWAITING_REPORT_APPROVAL,
            S.WRITING,
            S.RESEARCHING,
            S.NEEDS_ATTENTION,
            S.FAILED,
        }
    ),
    S.AWAITING_REPORT_APPROVAL: frozenset(
        # A rejected report is never exportable as approved; it needs attention.
        {S.SUCCEEDED, S.NEEDS_ATTENTION, S.CANCELLED, S.EXPIRED}
    ),
    # In-flight calls may finish; their results are recorded but no new work is scheduled.
    S.CANCEL_REQUESTED: frozenset({S.CANCELLED, S.FAILED}),
    **{state: frozenset() for state in TERMINAL_STATES},
}
for _state in _ACTIVE:
    ALLOWED_TRANSITIONS[_state] = ALLOWED_TRANSITIONS[_state] | {
        S.CANCEL_REQUESTED,
        S.EXPIRED,
    }

# Only a human retry (POST /runs/{id}/retry) re-opens a failed run, returning it to the state
# it failed in so the workflow resumes from its last checkpoint. Workers never leave FAILED.
RETRYABLE_FROM = frozenset({S.QUEUED, *_ACTIVE})
ALLOWED_TRANSITIONS[S.FAILED] = RETRYABLE_FROM


class InvalidTransition(ValueError):
    pass


def check_transition(current: RunState, target: RunState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"{current} -> {target} is not allowed")


def route_after_review(outcome: ReviewOutcome, review_round: int) -> RunState:
    """At most two review/revision rounds overall; exhaustion is an explicit outcome."""
    if not 1 <= review_round <= MAX_REVIEW_ROUNDS:
        raise ValueError(f"review_round must be 1..{MAX_REVIEW_ROUNDS}")
    if outcome == "pass":
        return S.AWAITING_REPORT_APPROVAL
    if review_round >= MAX_REVIEW_ROUNDS:
        return S.NEEDS_ATTENTION
    return S.WRITING if outcome == "revise" else S.RESEARCHING
