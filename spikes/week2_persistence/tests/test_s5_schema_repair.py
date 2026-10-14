"""S5: one bounded schema-repair attempt; persistent invalid output is a visible failure."""

import pytest

from app.contracts import Plan
from spike.fakes import FAKE_PLAN, INVALID_PLAN_OUTPUTS, SchemaRepairExhausted, call_structured, planner_model
from tests.conftest import count, job, run_state, run_worker_process


def test_valid_output_needs_no_repair() -> None:
    plan, attempts = call_structured(planner_model("valid"), Plan, "p")
    assert attempts == 1 and plan.tasks[0].task_id == FAKE_PLAN["tasks"][0]["task_id"]


def test_one_repair_then_success_without_echoing_model_output() -> None:
    model = planner_model("invalid_once")
    _, attempts = call_structured(model, Plan, "p")
    assert attempts == 2 and len(model.prompts) == 2
    assert "invalid" in model.prompts[1]
    assert INVALID_PLAN_OUTPUTS[0] not in model.prompts[1]


def test_repair_is_bounded() -> None:
    model = planner_model("invalid_always")
    with pytest.raises(SchemaRepairExhausted) as info:
        call_structured(model, Plan, "p")
    assert info.value.attempts == 2 and len(model.prompts) == 2


def test_persistent_invalid_output_fails_run_visibly(conn, new_run) -> None:
    run_id = new_run()
    assert run_worker_process(run_id, "w1", planner_mode="invalid_always") == (0, "failed")
    assert run_state(conn, run_id) == "FAILED"
    assert job(conn, run_id)["state"] == "FAILED"
    event = conn.execute(
        "SELECT payload FROM run_events WHERE run_id = %s AND event_type = 'step_failed'", (run_id,)
    ).fetchone()
    assert event["payload"]["step"] == "planner"
    assert "invalid output after 2 attempts" in event["payload"]["reason"]
    assert count(conn, "SELECT 1 FROM plan_versions WHERE run_id = %s", run_id) == 0


def test_repaired_output_is_recorded(conn, new_run) -> None:
    run_id = new_run()
    assert run_worker_process(run_id, "w1", planner_mode="invalid_once") == (0, "waiting_plan")
    event = conn.execute(
        "SELECT payload FROM run_events WHERE run_id = %s AND event_type = 'plan_proposed'", (run_id,)
    ).fetchone()
    assert event["payload"]["model_attempts"] == 2
