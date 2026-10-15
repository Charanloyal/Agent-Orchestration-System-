"""M9: cancellation, retry, the attempts reaper, and segment deadlines (FR-10, ADR 0015)."""

import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.agents.base import AgentCall, EvidenceView, ResearchTools
from app.agents.fake import FakeResearcher, FakeWriter, fake_agents
from app.config import get_settings
from app.contracts import Brief, Plan, PlanTask, ResearcherOutput, ReviewFinding, WriterOutput
from app.db.models import ReportVersion, Role, Run, RunJob, TaskResult, ToolExecution, User, Workspace
from app.db.session import get_sessionmaker
from app.services.runs import MAX_MANUAL_RETRIES
from app.workers import jobs
from app.workers.maintenance import reap_exhausted_jobs
from app.workers.runner import process_one
from app.workflow.errors import StepFailed
from tests.conftest import LoggedIn
from tests.test_workflow import decide, start_run


@pytest.fixture
def team(
    make_user: Callable[..., User], make_workspace: Callable[..., Workspace], checkpointer_ready: None
) -> dict[str, Any]:
    analyst, reviewer = make_user("Ana"), make_user("Rev")
    workspace = make_workspace("Team", {analyst: Role.ANALYST, reviewer: Role.REVIEWER})
    return {"analyst": analyst, "reviewer": reviewer, "workspace": workspace}


def work(run_id: str, **deps: Any) -> str:
    return process_one(get_settings(), run_id=uuid.UUID(run_id), **deps)


def cancel(client: TestClient, session: LoggedIn, run_id: str) -> Any:
    return client.post(f"/api/v1/runs/{run_id}/cancel", headers=session.headers)


def retry(client: TestClient, session: LoggedIn, run_id: str) -> Any:
    return client.post(f"/api/v1/runs/{run_id}/retry", headers=session.headers)


def states(client: TestClient, run_id: str) -> list[str]:
    timeline = client.get(f"/api/v1/runs/{run_id}/timeline").json()
    return [e["payload"]["to"] for e in timeline if e["type"] == "state_changed"]


def job(db: Session, run_id: str) -> RunJob:
    db.expire_all()
    row = db.get(RunJob, uuid.UUID(run_id))
    assert row is not None
    return row


# --- Cancellation ----------------------------------------------------------------------------


def test_cancelling_a_queued_run_is_immediate_and_idempotent(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    response = cancel(client, analyst, run_id)
    assert response.status_code == 200 and response.json()["state"] == "CANCELLED"
    assert response.json()["outcome_reason"] == "Cancelled by analyst"
    assert cancel(client, analyst, run_id).json()["state"] == "CANCELLED", "repeat cancels are no-ops"
    assert job(db, run_id).state == "DONE"
    assert work(run_id) == "no_job", "a cancelled run is never claimed"


def test_cancelling_while_awaiting_approval_blocks_the_decision(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert work(run_id) == "waiting_plan"
    pending = client.get(f"/api/v1/runs/{run_id}").json()["pending_decision"]
    assert cancel(client, analyst, run_id).json()["state"] == "CANCELLED"
    late = client.post(
        f"/api/v1/runs/{run_id}/plan-decisions",
        json={"version": pending["version"], "digest": pending["digest"], "decision": "approve"},
        headers=analyst.headers,
    )
    assert late.status_code == 409
    assert states(client, run_id)[-2:] == ["AWAITING_PLAN_APPROVAL", "CANCELLED"]


class CancelsDuringResearch(FakeResearcher):
    """Simulates a human pressing Cancel while the first research task is running."""

    def __init__(self, do_cancel: Callable[[], Any]) -> None:
        self.do_cancel = do_cancel
        self.cancelled = False

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        if not self.cancelled:
            self.cancelled = True
            assert self.do_cancel().json()["state"] == "CANCEL_REQUESTED", "a running run is asked to stop"
        return super().research(brief, task, tools)


def test_cancelling_a_running_run_stops_at_the_next_boundary(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert work(run_id) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    researcher = CancelsDuringResearch(lambda: cancel(client, analyst, run_id))
    assert work(run_id, agents=replace(fake_agents(), researcher=researcher)) == "cancelled"

    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "CANCELLED" and "next step boundary" in detail["outcome_reason"]
    assert states(client, run_id)[-3:] == ["RESEARCHING", "CANCEL_REQUESTED", "CANCELLED"]
    assert job(db, run_id).state == "DONE" and job(db, run_id).lease_owner is None
    assert (
        db.scalar(
            select(func.count()).select_from(ReportVersion).where(ReportVersion.run_id == uuid.UUID(run_id))
        )
        == 0
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(ToolExecution)
            .where(ToolExecution.run_id == uuid.UUID(run_id), ToolExecution.status == "started")
        )
        == 0
    ), "no new tool call started after the request"


def test_reviewers_cannot_cancel_and_finished_runs_cannot_be_cancelled(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    reviewer = login(team["reviewer"])
    assert cancel(client, reviewer, run_id).status_code == 403
    analyst = login(team["analyst"])
    assert cancel(client, analyst, run_id).status_code == 200
    with get_sessionmaker()() as s:
        s.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(state="SUCCEEDED"))
        s.commit()
    assert cancel(client, analyst, run_id).status_code == 409


# --- Retry -----------------------------------------------------------------------------------


class FlakyWriter(FakeWriter):
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def write(
        self,
        brief: Brief,
        plan: Plan,
        evidence: list[EvidenceView],
        *,
        report_version: int,
        findings: list[ReviewFinding],
    ) -> AgentCall[WriterOutput]:
        if self.failures:
            self.failures -= 1
            raise StepFailed("writer", "invalid model output after 2 attempts")
        return super().write(brief, plan, evidence, report_version=report_version, findings=findings)


def test_retry_resumes_a_failed_run_from_its_checkpoint_without_redoing_research(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert work(run_id) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    agents = replace(fake_agents(), writer=FlakyWriter(failures=1))
    assert work(run_id, agents=agents) == "failed"
    failed = client.get(f"/api/v1/runs/{run_id}").json()
    assert failed["state"] == "FAILED" and failed["outcome_reason"].startswith("writer:")
    db.expire_all()
    tasks = db.scalar(
        select(func.count()).select_from(TaskResult).where(TaskResult.run_id == uuid.UUID(run_id))
    )
    calls = db.scalar(
        select(func.count()).select_from(ToolExecution).where(ToolExecution.run_id == uuid.UUID(run_id))
    )

    retried = retry(client, analyst, run_id)
    assert retried.status_code == 200, retried.text
    assert retried.json()["state"] == "WRITING" and retried.json()["outcome_reason"] is None
    assert retried.json()["job"]["state"] == "QUEUED"
    assert retry(client, analyst, run_id).status_code == 409, "only failed runs can be retried"

    assert work(run_id, agents=agents) == "waiting_report"
    db.expire_all()
    assert (
        db.scalar(select(func.count()).select_from(TaskResult).where(TaskResult.run_id == uuid.UUID(run_id)))
        == tasks
    )
    assert (
        db.scalar(
            select(func.count()).select_from(ToolExecution).where(ToolExecution.run_id == uuid.UUID(run_id))
        )
        == calls
    ), "research is not repeated"
    assert states(client, run_id)[-4:] == ["FAILED", "WRITING", "REVIEWING", "AWAITING_REPORT_APPROVAL"]
    retried_events = [
        e for e in client.get(f"/api/v1/runs/{run_id}/timeline").json() if e["type"] == "run_retried"
    ]
    assert retried_events[0]["payload"] == {"role": "analyst", "resume_state": "WRITING", "retry": 1}


def test_manual_retries_are_bounded(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert work(run_id) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    agents = replace(fake_agents(), writer=FlakyWriter(failures=99))
    assert work(run_id, agents=agents) == "failed"
    for _ in range(MAX_MANUAL_RETRIES):
        assert retry(client, analyst, run_id).status_code == 200
        assert work(run_id, agents=agents) == "failed"
    blocked = retry(client, analyst, run_id)
    assert blocked.status_code == 409 and "already retried" in blocked.json()["error"]["message"]


# --- Reaper and deadlines --------------------------------------------------------------------


def test_reaper_fails_jobs_whose_workers_keep_crashing_and_fences_them_off(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    sm = get_sessionmaker()
    with sm() as s:
        s.execute(
            update(RunJob).where(RunJob.run_id == uuid.UUID(run_id)).values(attempts=RunJob.max_attempts - 1)
        )
        s.commit()
    lease = jobs.claim(sm, "doomed-worker", 30, uuid.UUID(run_id))
    assert lease is not None and lease.attempts == job(db, run_id).max_attempts
    with jobs.fenced(sm, lease) as s:
        s.add(
            ToolExecution(
                run_id=lease.run_id,
                task_id="t1",
                tool="web_search:fake",
                status="started",
                fencing_token=lease.token,
            )
        )
    assert reap_exhausted_jobs(sm) == 0, "a live lease is never reaped"
    with sm() as s:
        s.execute(
            update(RunJob)
            .where(RunJob.run_id == lease.run_id)
            .values(lease_expires_at=func.now() - text("interval '1 second'"))
        )
        s.commit()
    assert work(run_id) == "no_job", "the claim query skips exhausted jobs"
    assert reap_exhausted_jobs(sm) == 1

    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "FAILED" and "crashed or stalled" in detail["outcome_reason"]
    reaped = job(db, run_id)
    assert reaped.state == "FAILED" and reaped.fencing_token == lease.token + 1
    with pytest.raises(jobs.StaleOwner), jobs.fenced(sm, lease):
        pass
    assert {
        t.status for t in db.scalars(select(ToolExecution).where(ToolExecution.run_id == lease.run_id))
    } == {"abandoned"}
    assert retry(client, analyst, run_id).json()["state"] == "QUEUED", "a reaped run can be retried"
    assert work(run_id) == "waiting_plan"


def test_a_run_past_its_segment_deadline_expires_at_the_next_boundary(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert work(run_id) == "waiting_plan"
    with get_sessionmaker()() as s:
        s.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(deadline_at=func.now() - text("interval '1 minute'"))
        )
        s.commit()
    assert decide(client, analyst, run_id, "plan").status_code == 201
    db.expire_all()
    run = db.get(Run, uuid.UUID(run_id))
    assert run is not None and run.deadline_at > db.scalar(select(func.now())), (
        "a decision starts a new segment"
    )

    with get_sessionmaker()() as s:
        s.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(deadline_at=func.now() - text("interval '1 minute'"))
        )
        s.commit()
    assert work(run_id) == "expired"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "EXPIRED" and "deadline" in detail["outcome_reason"]
    assert (
        db.scalar(
            select(func.count()).select_from(ToolExecution).where(ToolExecution.run_id == uuid.UUID(run_id))
        )
        == 0
    )
