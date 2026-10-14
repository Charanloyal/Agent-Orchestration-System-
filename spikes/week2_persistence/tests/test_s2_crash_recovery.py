"""S2: kill the worker at defined crash windows and restart from the last checkpoint."""

from spike.graph import CRASH_POINTS
from tests.conftest import count, job, latest, run_worker_process, wait_for_lease_expiry
from tests.test_s1_pause_resume import approve

LEASE = 2  # seconds; short so the test can wait for real expiry


def run_to_approved_plan(conn, new_run) -> str:
    run_id = new_run()
    assert run_worker_process(run_id, "w-plan") == (0, "waiting_plan")
    approve(conn, run_id, "plan")
    return run_id


def crash_then_recover(conn, run_id: str, crash_at: str) -> None:
    assert crash_at in CRASH_POINTS
    rc, outcome = run_worker_process(run_id, "w-crash", crash_at=crash_at, lease_seconds=LEASE)
    assert (rc, outcome) == (137, None), "worker should die abruptly"
    assert job(conn, run_id)["state"] == "LEASED", "dead worker still holds an (expiring) lease"
    assert run_worker_process(run_id, "w-early") == (0, "no_job"), "unexpired lease must block takeover"
    wait_for_lease_expiry(conn, run_id)
    assert run_worker_process(run_id, "w-recover") == (0, "waiting_report")


def tool_calls(conn, run_id: str, status: str | None = None) -> int:
    if status:
        return count(conn, "SELECT 1 FROM tool_executions WHERE run_id = %s AND status = %s", run_id, status)
    return count(conn, "SELECT 1 FROM tool_executions WHERE run_id = %s", run_id)


def test_crash_after_external_call_before_commit_repeats_that_call(conn, new_run) -> None:
    run_id = run_to_approved_plan(conn, new_run)
    crash_then_recover(conn, run_id, "after_search_before_commit")

    assert count(conn, "SELECT 1 FROM evidence WHERE run_id = %s", run_id) == 6
    # Honest at-least-once: the interrupted call ran twice and the first is marked abandoned.
    assert tool_calls(conn, run_id) == 4
    assert tool_calls(conn, run_id, "abandoned") == 1
    assert tool_calls(conn, run_id, "succeeded") == 3


def test_crash_after_evidence_commit_does_not_duplicate_evidence_or_calls(conn, new_run) -> None:
    run_id = run_to_approved_plan(conn, new_run)
    crash_then_recover(conn, run_id, "after_evidence_commit")

    assert count(conn, "SELECT 1 FROM evidence WHERE run_id = %s", run_id) == 6
    assert tool_calls(conn, run_id) == 3, "committed tasks are not re-executed"
    assert count(conn, "SELECT 1 FROM report_versions WHERE run_id = %s", run_id) == 1


def test_crash_before_writer_resumes_at_writer(conn, new_run) -> None:
    run_id = run_to_approved_plan(conn, new_run)
    crash_then_recover(conn, run_id, "before_writer")

    assert tool_calls(conn, run_id) == 3
    assert count(
        conn, "SELECT 1 FROM run_events WHERE run_id = %s AND event_type = 'task_completed'", run_id
    ) == 3
    assert count(conn, "SELECT 1 FROM report_versions WHERE run_id = %s", run_id) == 1


def test_crash_after_report_commit_keeps_first_committed_version(conn, new_run) -> None:
    run_id = run_to_approved_plan(conn, new_run)
    rc, _ = run_worker_process(run_id, "w-crash", crash_at="after_report_commit", lease_seconds=LEASE)
    assert rc == 137
    committed = latest(conn, "report_versions", run_id)

    wait_for_lease_expiry(conn, run_id)
    assert run_worker_process(run_id, "w-recover") == (0, "waiting_report")
    assert count(conn, "SELECT 1 FROM report_versions WHERE run_id = %s", run_id) == 1
    assert latest(conn, "report_versions", run_id) == committed
    assert count(
        conn, "SELECT 1 FROM run_events WHERE run_id = %s AND event_type = 'report_drafted'", run_id
    ) == 1
