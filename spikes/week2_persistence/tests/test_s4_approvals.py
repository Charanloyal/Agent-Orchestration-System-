"""S4: approvals bind to version and digest, are single-winner, and schedule resumption."""

import threading

import pytest

from app.contracts import StaleApproval
from spike.approvals import NotAwaitingDecision, decide
from spike.db import connect
from tests.conftest import count, job, latest, run_worker_process


def test_decision_rejected_when_run_is_not_waiting(conn, new_run) -> None:
    run_id = new_run()
    with pytest.raises(NotAwaitingDecision):
        decide(conn, run_id, kind="plan", version=1, digest="0" * 64, decision="approve", decided_by="x")


def test_wrong_kind_and_wrong_digest_rejected(conn, new_run) -> None:
    run_id = new_run()
    run_worker_process(run_id, "w1")
    plan = latest(conn, "plan_versions", run_id)
    with pytest.raises(NotAwaitingDecision):
        decide(conn, run_id, kind="report", version=1, digest=plan["digest"], decision="approve", decided_by="x")
    with pytest.raises(StaleApproval):
        decide(conn, run_id, kind="plan", version=1, digest="f" * 64, decision="approve", decided_by="x")
    assert count(conn, "SELECT 1 FROM approvals WHERE run_id = %s", run_id) == 0
    assert job(conn, run_id)["state"] == "WAITING"


def test_concurrent_approvals_have_exactly_one_winner(conn, new_run) -> None:
    run_id = new_run()
    run_worker_process(run_id, "w1")
    plan = latest(conn, "plan_versions", run_id)
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def approve(n: int) -> None:
        with connect() as c:
            barrier.wait()
            try:
                decide(c, run_id, kind="plan", version=1, digest=plan["digest"], decision="approve",
                       decided_by=f"reviewer{n}@test")
                outcomes.append("ok")
            except NotAwaitingDecision:
                outcomes.append("rejected")

    threads = [threading.Thread(target=approve, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok", "rejected", "rejected", "rejected"]
    assert count(conn, "SELECT 1 FROM approvals WHERE run_id = %s", run_id) == 1


def test_decision_durably_schedules_resumption_without_a_worker(conn, new_run) -> None:
    run_id = new_run()
    run_worker_process(run_id, "w1")
    waiting = job(conn, run_id)
    assert waiting["lease_owner"] is None and waiting["lease_expires_at"] is None

    plan = latest(conn, "plan_versions", run_id)
    approval_id = decide(conn, run_id, kind="plan", version=1, digest=plan["digest"],
                         decision="approve", decided_by="x")
    queued = job(conn, run_id)
    assert queued["state"] == "QUEUED"
    assert queued["resume_payload"] == {"approval_id": approval_id}
    # Any worker, in any process, can now pick it up.
    assert run_worker_process(run_id, "some-other-worker") == (0, "waiting_report")
