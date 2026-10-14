"""S1: pause at each approval, release the worker, and resume in a fresh OS process."""

import pytest

from app.contracts import StaleApproval
from spike.approvals import decide
from spike.leases import claim
from tests.conftest import count, job, latest, run_state, run_worker_process, state_history


def approve(conn, run_id: str, kind: str) -> None:
    table = "plan_versions" if kind == "plan" else "report_versions"
    current = latest(conn, table, run_id)
    decide(conn, run_id, kind=kind, version=current["version"], digest=current["digest"],
           decision="approve", decided_by="analyst@test")


def test_full_run_across_three_processes(conn, new_run) -> None:
    run_id = new_run()

    assert run_worker_process(run_id, "w1") == (0, "waiting_plan")
    waiting = job(conn, run_id)
    assert (waiting["state"], waiting["waiting_for"], waiting["lease_owner"]) == ("WAITING", "plan", None)
    assert run_state(conn, run_id) == "AWAITING_PLAN_APPROVAL"
    assert claim(conn, "idle-worker", 30, run_id) is None, "a waiting run must not be claimable"

    approve(conn, run_id, "plan")
    assert run_worker_process(run_id, "w2") == (0, "waiting_report")
    assert count(conn, "SELECT 1 FROM evidence WHERE run_id = %s", run_id) == 6
    assert count(conn, "SELECT 1 FROM report_versions WHERE run_id = %s", run_id) == 1
    assert job(conn, run_id)["lease_owner"] is None

    approve(conn, run_id, "report")
    assert run_worker_process(run_id, "w3") == (0, "done")

    assert run_state(conn, run_id) == "SUCCEEDED"
    assert job(conn, run_id)["state"] == "DONE"
    assert state_history(conn, run_id) == [
        "PLANNING",
        "AWAITING_PLAN_APPROVAL",
        "RESEARCHING",
        "WRITING",
        "REVIEWING",
        "AWAITING_REPORT_APPROVAL",
        "SUCCEEDED",
    ]
    assert count(
        conn, "SELECT 1 FROM tool_executions WHERE run_id = %s AND status = 'succeeded'", run_id
    ) == 3


def test_plan_rejection_creates_new_version_and_stale_decisions_fail(conn, new_run) -> None:
    run_id = new_run()
    assert run_worker_process(run_id, "w1") == (0, "waiting_plan")
    v1 = latest(conn, "plan_versions", run_id)
    decide(conn, run_id, kind="plan", version=1, digest=v1["digest"], decision="reject",
           decided_by="analyst@test")

    assert run_worker_process(run_id, "w2") == (0, "waiting_plan")
    v2 = latest(conn, "plan_versions", run_id)
    assert v2["version"] == 2 and v2["digest"] != v1["digest"]

    with pytest.raises(StaleApproval, match="version"):
        decide(conn, run_id, kind="plan", version=1, digest=v1["digest"], decision="approve",
               decided_by="analyst@test")
    with pytest.raises(StaleApproval, match="digest"):
        decide(conn, run_id, kind="plan", version=2, digest=v1["digest"], decision="approve",
               decided_by="analyst@test")

    approve(conn, run_id, "plan")
    assert run_worker_process(run_id, "w3") == (0, "waiting_report")
    assert state_history(conn, run_id)[:4] == [
        "PLANNING", "AWAITING_PLAN_APPROVAL", "PLANNING", "AWAITING_PLAN_APPROVAL"
    ]


def test_report_rejection_needs_attention_not_success(conn, new_run) -> None:
    run_id = new_run()
    run_worker_process(run_id, "w1")
    approve(conn, run_id, "plan")
    run_worker_process(run_id, "w2")
    report = latest(conn, "report_versions", run_id)
    decide(conn, run_id, kind="report", version=report["version"], digest=report["digest"],
           decision="reject", decided_by="reviewer@test")
    assert run_worker_process(run_id, "w3") == (0, "done")
    assert run_state(conn, run_id) == "NEEDS_ATTENTION"
