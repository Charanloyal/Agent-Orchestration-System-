"""End-to-end workflow through the public API and the real worker (fake agents, real
PostgreSQL, real LangGraph checkpoints)."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import EvidencePassage, Role, RunJob, TaskResult, ToolExecution, User, Workspace
from app.workers.runner import process_one
from tests.conftest import SAMPLE_BRIEF, LoggedIn


@pytest.fixture
def team(
    make_user: Callable[..., User], make_workspace: Callable[..., Workspace], checkpointer_ready: None
) -> dict[str, Any]:
    analyst, reviewer = make_user("Ana"), make_user("Rev")
    workspace = make_workspace("Team", {analyst: Role.ANALYST, reviewer: Role.REVIEWER})
    return {"analyst": analyst, "reviewer": reviewer, "workspace": workspace}


def start_run(client: TestClient, session: LoggedIn, workspace: Workspace, key: str | None = None) -> str:
    response = client.post(
        "/api/v1/runs",
        json={"workspace_id": str(workspace.id), "brief": SAMPLE_BRIEF},
        headers={**session.headers, "Idempotency-Key": key or uuid.uuid4().hex},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def work(run_id: str) -> str:
    return process_one(get_settings(), run_id=uuid.UUID(run_id))


def decide(
    client: TestClient, session: LoggedIn, run_id: str, kind: str, decision: str = "approve", **override: Any
) -> Any:
    pending = client.get(f"/api/v1/runs/{run_id}").json()["pending_decision"]
    body = {"version": pending["version"], "digest": pending["digest"], "decision": decision, **override}
    url = f"/api/v1/runs/{run_id}/plan-decisions" if kind == "plan" else f"/api/v1/reports/{run_id}/decisions"
    return client.post(url, json=body, headers=session.headers)


def event_types(client: TestClient, run_id: str) -> list[str]:
    return [e["type"] for e in client.get(f"/api/v1/runs/{run_id}/timeline").json()]


def test_happy_path_brief_to_approved_report(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert client.get(f"/api/v1/runs/{run_id}").json()["state"] == "QUEUED"

    assert work(run_id) == "waiting_plan"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "AWAITING_PLAN_APPROVAL"
    assert detail["job"]["state"] == "WAITING" and detail["pending_decision"]["kind"] == "plan"
    assert detail["plan"]["version"] == 1 and len(detail["plan"]["body"]["tasks"]) >= 1
    assert work(run_id) == "no_job", "a run waiting for a human must not be claimable"

    assert decide(client, analyst, run_id, "plan").status_code == 201
    assert work(run_id) == "waiting_report"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "AWAITING_REPORT_APPROVAL"
    report = detail["report"]["body"]
    evidence_ids = {e["evidence_id"] for e in client.get(f"/api/v1/runs/{run_id}/evidence").json()}
    cited = {eid for s in report["sections"] for c in s["claims"] for eid in c["evidence_ids"]}
    assert cited and cited <= evidence_ids, "every citation resolves to run evidence"

    reviewer = login(team["reviewer"])
    assert decide(client, reviewer, run_id, "report").status_code == 201
    assert work(run_id) == "done"

    final = client.get(f"/api/v1/runs/{run_id}").json()
    assert final["state"] == "SUCCEEDED"
    assert [d["kind"] for d in final["decisions"]] == ["plan", "report"]
    states = [
        e["payload"]["to"]
        for e in client.get(f"/api/v1/runs/{run_id}/timeline").json()
        if e["type"] == "state_changed"
    ]
    assert states == [
        "PLANNING",
        "AWAITING_PLAN_APPROVAL",
        "RESEARCHING",
        "WRITING",
        "REVIEWING",
        "AWAITING_REPORT_APPROVAL",
        "SUCCEEDED",
    ]
    assert (
        db.scalar(
            select(func.count())
            .select_from(ToolExecution)
            .where(ToolExecution.run_id == uuid.UUID(run_id), ToolExecution.status != "succeeded")
        )
        == 0
    )
    job = db.get(RunJob, uuid.UUID(run_id))
    assert job is not None and job.state == "DONE" and job.lease_owner is None


def test_idempotent_creation(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    body = {"workspace_id": str(team["workspace"].id), "brief": SAMPLE_BRIEF}
    headers = {**analyst.headers, "Idempotency-Key": "same-key-123"}
    first = client.post("/api/v1/runs", json=body, headers=headers)
    replay = client.post("/api/v1/runs", json=body, headers=headers)
    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.json()["id"] == replay.json()["id"]
    changed = {**body, "brief": {**SAMPLE_BRIEF, "topic": "A different topic entirely"}}
    assert client.post("/api/v1/runs", json=changed, headers=headers).status_code == 409


@pytest.mark.parametrize(
    "brief_patch",
    [
        {"limits": {"max_review_rounds": 5}},
        {"budget": {"max_estimated_cost": "0"}},
        {"research_questions": []},
        {"unexpected": "field"},
    ],
)
def test_invalid_briefs_rejected(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn], brief_patch: dict[str, Any]
) -> None:
    analyst = login(team["analyst"])
    response = client.post(
        "/api/v1/runs",
        json={"workspace_id": str(team["workspace"].id), "brief": {**SAMPLE_BRIEF, **brief_patch}},
        headers={**analyst.headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 422


def test_role_separation(client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    work(run_id)
    reviewer = login(team["reviewer"])
    assert (
        client.post(
            "/api/v1/runs",
            json={"workspace_id": str(team["workspace"].id), "brief": SAMPLE_BRIEF},
            headers={**reviewer.headers, "Idempotency-Key": uuid.uuid4().hex},
        ).status_code
        == 403
    )
    assert decide(client, reviewer, run_id, "plan").status_code == 403


def test_stale_and_wrong_kind_decisions_rejected(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    work(run_id)
    assert decide(client, analyst, run_id, "plan", digest="f" * 64).status_code == 409
    assert decide(client, analyst, run_id, "plan", version=7).status_code == 409
    assert (
        client.post(
            f"/api/v1/reports/{run_id}/decisions",
            json={"version": 1, "digest": "0" * 64, "decision": "approve"},
            headers=login(team["reviewer"]).headers,
        ).status_code
        == 409
    )
    analyst = login(team["analyst"])
    pending = client.get(f"/api/v1/runs/{run_id}").json()["pending_decision"]
    body = {"version": pending["version"], "digest": pending["digest"], "decision": "approve"}
    url = f"/api/v1/runs/{run_id}/plan-decisions"
    assert client.post(url, json=body, headers=analyst.headers).status_code == 201
    replay = client.post(url, json=body, headers=analyst.headers)
    assert replay.status_code == 409, "second decision on the same wait is rejected"


def test_plan_rejection_creates_new_version(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    work(run_id)
    v1 = client.get(f"/api/v1/runs/{run_id}").json()["plan"]
    assert decide(client, analyst, run_id, "plan", "reject", comment="Focus on security").status_code == 201
    assert work(run_id) == "waiting_plan"
    v2 = client.get(f"/api/v1/runs/{run_id}").json()["plan"]
    assert v2["version"] == 2 and v2["digest"] != v1["digest"]
    assert any("Focus on security" in a for a in v2["body"]["assumptions"])
    assert client.get(f"/api/v1/runs/{run_id}/plans/1").json()["digest"] == v1["digest"], "v1 is immutable"


def test_report_rejection_needs_attention(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    work(run_id)
    decide(client, analyst, run_id, "plan")
    work(run_id)
    assert decide(client, login(team["reviewer"]), run_id, "report", "reject").status_code == 201
    assert work(run_id) == "done"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "NEEDS_ATTENTION" and "rejected" in detail["outcome_reason"]


def test_sse_replays_and_resumes_after_last_event_id(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    work(run_id)
    decide(client, analyst, run_id, "plan", "reject")
    # Drive to a terminal state so the stream ends by itself.
    from sqlalchemy import update

    from app.db.models import Run
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        s.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(state="CANCELLED"))
        s.commit()

    def read_stream(headers: dict[str, str]) -> list[dict[str, Any]]:
        events = []
        with client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=headers) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("data: ") and '"type"' in line:
                    events.append(json.loads(line[6:]))
        return events

    all_events = read_stream({})
    assert [e["id"] for e in all_events] == sorted(e["id"] for e in all_events)
    assert {e["type"] for e in all_events} >= {"run_created", "plan_proposed", "decision_recorded"}
    middle = all_events[len(all_events) // 2]["id"]
    resumed = read_stream({"Last-Event-ID": str(middle)})
    assert [e["id"] for e in resumed] == [e["id"] for e in all_events if e["id"] > middle]


def test_research_results_are_recorded_once_per_task(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    work(run_id)
    decide(client, analyst, run_id, "plan")
    work(run_id)
    rid = uuid.UUID(run_id)
    plan_tasks = len(client.get(f"/api/v1/runs/{run_id}").json()["plan"]["body"]["tasks"])
    assert (
        db.scalar(select(func.count()).select_from(TaskResult).where(TaskResult.run_id == rid)) == plan_tasks
    )
    assert (
        db.scalar(select(func.count()).select_from(EvidencePassage).where(EvidencePassage.run_id == rid)) > 0
    )
    assert event_types(client, run_id).count("task_completed") == plan_tasks
