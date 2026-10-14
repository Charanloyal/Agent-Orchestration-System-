import pytest

from app.contracts import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    WAITING_STATES,
    InvalidTransition,
    RunState,
    check_transition,
    route_after_review,
)

S = RunState


def test_every_state_has_a_transition_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(RunState)


def test_terminal_states_have_no_exits() -> None:
    for state in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[state] == frozenset()


def test_every_non_terminal_state_can_reach_a_terminal_state() -> None:
    for start in set(RunState) - TERMINAL_STATES:
        seen, frontier = {start}, [start]
        while frontier:
            for nxt in ALLOWED_TRANSITIONS[frontier.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        assert seen & TERMINAL_STATES, start


def test_happy_path_is_allowed() -> None:
    path = [
        S.QUEUED,
        S.PLANNING,
        S.AWAITING_PLAN_APPROVAL,
        S.RESEARCHING,
        S.WRITING,
        S.REVIEWING,
        S.AWAITING_REPORT_APPROVAL,
        S.SUCCEEDED,
    ]
    for current, target in zip(path, path[1:]):
        check_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.PLANNING, S.RESEARCHING),  # research cannot start without plan approval
        (S.REVIEWING, S.SUCCEEDED),  # success requires human report approval
        (S.WRITING, S.SUCCEEDED),
        (S.SUCCEEDED, S.PLANNING),
        (S.CANCEL_REQUESTED, S.RESEARCHING),  # cancellation stops new work
        (S.NEEDS_ATTENTION, S.SUCCEEDED),
    ],
)
def test_forbidden_transitions(current: RunState, target: RunState) -> None:
    with pytest.raises(InvalidTransition):
        check_transition(current, target)


def test_active_states_can_request_cancellation_and_waits_cancel_directly() -> None:
    for state in (S.PLANNING, S.RESEARCHING, S.WRITING, S.REVIEWING):
        check_transition(state, S.CANCEL_REQUESTED)
    for state in WAITING_STATES:
        check_transition(state, S.CANCELLED)
        check_transition(state, S.EXPIRED)


@pytest.mark.parametrize(
    ("outcome", "review_round", "expected"),
    [
        ("pass", 1, S.AWAITING_REPORT_APPROVAL),
        ("pass", 2, S.AWAITING_REPORT_APPROVAL),
        ("revise", 1, S.WRITING),
        ("insufficient_evidence", 1, S.RESEARCHING),
        ("revise", 2, S.NEEDS_ATTENTION),
        ("insufficient_evidence", 2, S.NEEDS_ATTENTION),
    ],
)
def test_review_routing_is_bounded(outcome: str, review_round: int, expected: RunState) -> None:
    assert route_after_review(outcome, review_round) == expected  # type: ignore[arg-type]
    check_transition(S.REVIEWING, expected)


def test_review_round_out_of_range() -> None:
    with pytest.raises(ValueError):
        route_after_review("revise", 3)
