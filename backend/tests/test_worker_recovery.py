"""Production worker recovery and fencing (ADR 0007/0008), using real OS processes for crashes.

The full 10-scenario crash suite is completed in M9; these are the core guarantees.
"""

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any, TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.agents.base import AgentCall, ResearchTools
from app.agents.fake import FakePlanner, fake_agents
from app.config import get_settings
from app.contracts import Brief, Plan, PlanTask, ResearcherOutput
from app.db.models import (
    EvidencePassage,
    ReportVersion,
    Role,
    RunJob,
    TaskResult,
    ToolExecution,
    User,
    Workspace,
)
from app.db.session import get_sessionmaker
from app.workers import jobs
from app.workers.checkpointer import FencedPostgresSaver, checkpoint_connection
from app.workers.jobs import StaleOwner
from app.workers.runner import process_one
from app.workflow.errors import StepFailed, TransientError
from tests.conftest import BACKEND_DIR, LoggedIn
from tests.test_workflow import decide, start_run


@pytest.fixture
def team(
    make_user: Callable[..., User], make_workspace: Callable[..., Workspace], checkpointer_ready: None
) -> dict[str, Any]:
    analyst, reviewer = make_user("Ana"), make_user("Rev")
    return {
        "analyst": analyst,
        "reviewer": reviewer,
        "workspace": make_workspace("Team", {analyst: Role.ANALYST, reviewer: Role.REVIEWER}),
    }


def worker_process(run_id: str, *, crash_at: str | None = None, lease_seconds: float = 30) -> tuple[int, str]:
    env = {**os.environ, "AOS_WORKER_LEASE_SECONDS": str(lease_seconds)}
    if crash_at:
        env["AOS_CRASH_AT"] = crash_at
    proc = subprocess.run(
        [sys.executable, "-m", "app.workers.runner", "--once", "--run-id", run_id],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode not in (0, 137):
        raise AssertionError(f"worker rc={proc.returncode}\n{proc.stderr[-3000:]}")
    return proc.returncode, proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""


def expire_lease(run_id: str) -> None:
    with get_sessionmaker()() as s:
        s.execute(
            update(RunJob)
            .where(RunJob.run_id == uuid.UUID(run_id))
            .values(lease_expires_at=func.now() - text("interval '1 second'"))
        )
        s.commit()


def counts(db: Session, run_id: str) -> dict[str, int]:
    rid = uuid.UUID(run_id)
    db.expire_all()
    return {
        "evidence": db.scalar(
            select(func.count()).select_from(EvidencePassage).where(EvidencePassage.run_id == rid)
        )
        or 0,
        "tasks": db.scalar(select(func.count()).select_from(TaskResult).where(TaskResult.run_id == rid)) or 0,
        "reports": db.scalar(
            select(func.count()).select_from(ReportVersion).where(ReportVersion.run_id == rid)
        )
        or 0,
        "tool_calls": db.scalar(
            select(func.count()).select_from(ToolExecution).where(ToolExecution.run_id == rid)
        )
        or 0,
    }


def approved_plan_run(client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]) -> str:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert worker_process(run_id) == (0, "waiting_plan")
    assert decide(client, analyst, run_id, "plan").status_code == 201
    return run_id


@pytest.mark.parametrize("crash_at", ["after_research", "before_writer", "after_report_commit"])
def test_crash_and_restart_never_duplicates_committed_work(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn], crash_at: str
) -> None:
    run_id = approved_plan_run(client, team, login)
    rc, _ = worker_process(run_id, crash_at=crash_at)
    assert rc == 137, "worker must die abruptly"
    after_crash = counts(db, run_id)
    assert after_crash["tasks"] > 0 and after_crash["evidence"] > 0

    assert worker_process(run_id) == (0, "no_job"), "unexpired lease blocks takeover"
    expire_lease(run_id)
    assert worker_process(run_id) == (0, "waiting_report")

    recovered = counts(db, run_id)
    assert recovered["evidence"] == after_crash["evidence"]
    assert recovered["tasks"] == after_crash["tasks"]
    assert recovered["tool_calls"] == after_crash["tool_calls"], "committed tasks are not re-executed"
    assert recovered["reports"] == 1
    if crash_at == "after_report_commit":
        assert after_crash["reports"] == 1, "first committed report version wins"


class Counter(TypedDict):
    value: int


def tiny_graph(saver: PostgresSaver) -> Any:
    builder: StateGraph[Any, Any, Any, Any] = StateGraph(Counter)
    builder.add_node("inc", lambda s: {"value": s["value"] + 1})
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)
    return builder.compile(checkpointer=saver)


def checkpoint_rows(thread_id: str) -> int:
    with checkpoint_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s", (thread_id,)
        ).fetchone()
        return int(row["n"]) if row else 0


def test_stale_owner_cannot_write_checkpoints_but_unfenced_saver_can(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = uuid.UUID(start_run(client, login(team["analyst"]), team["workspace"]))
    sm = get_sessionmaker()
    stale = jobs.claim(sm, "A", 30, run_id)
    assert stale is not None
    expire_lease(str(run_id))
    current = jobs.claim(sm, "B", 30, run_id)
    assert current is not None and current.token == stale.token + 1
    config = {"configurable": {"thread_id": str(run_id)}}

    with checkpoint_connection(get_settings()) as conn, pytest.raises(StaleOwner):
        tiny_graph(FencedPostgresSaver(conn, run_id=run_id, fencing_token=stale.token)).invoke(
            {"value": 0}, config, durability="sync"
        )
    assert checkpoint_rows(str(run_id)) == 0

    negative = str(uuid.uuid4())  # negative control: the stock saver has no fence at all
    with checkpoint_connection(get_settings()) as conn:
        tiny_graph(PostgresSaver(conn)).invoke(
            {"value": 0}, {"configurable": {"thread_id": negative}}, durability="sync"
        )
    assert checkpoint_rows(negative) > 0

    with checkpoint_connection(get_settings()) as conn:
        result = tiny_graph(FencedPostgresSaver(conn, run_id=run_id, fencing_token=current.token)).invoke(
            {"value": 0}, config, durability="sync"
        )
    assert result == {"value": 1} and checkpoint_rows(str(run_id)) > 0

    with pytest.raises(StaleOwner), jobs.fenced(sm, stale):
        pass
    with pytest.raises(StaleOwner):
        jobs.heartbeat(sm, stale, 30)


def test_concurrent_claims_have_one_winner(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = uuid.UUID(start_run(client, login(team["analyst"]), team["workspace"]))
    barrier, results = threading.Barrier(6), []

    def contend(n: int) -> None:
        barrier.wait()
        results.append(jobs.claim(get_sessionmaker(), f"w{n}", 30, run_id))

    threads = [threading.Thread(target=contend, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len([r for r in results if r is not None]) == 1


class FlakyResearcher:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def research(self, brief: Brief, task: PlanTask, tools: ResearchTools) -> AgentCall[ResearcherOutput]:
        raise self.error


def test_transient_errors_retry_with_backoff_then_fail_visibly(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = approved_plan_run(client, team, login)
    flaky = replace(fake_agents(), researcher=FlakyResearcher(TransientError("HTTP 429", retry_after=0.0)))
    settings = get_settings().model_copy(update={"job_max_attempts": 2, "retry_backoff_base_seconds": 0.0})
    rid = uuid.UUID(run_id)

    assert process_one(settings, run_id=rid, agents=flaky) == "retry"
    db.expire_all()
    job = db.get(RunJob, rid)
    assert (
        job is not None
        and job.state == "QUEUED"
        and job.lease_owner is None
        and "429" in (job.last_error or "")
    )
    time.sleep(0.05)
    assert process_one(settings, run_id=rid, agents=flaky) == "failed"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "FAILED" and "transient errors persisted" in detail["outcome_reason"]
    types = [e["type"] for e in client.get(f"/api/v1/runs/{run_id}/timeline").json()]
    assert types.count("retry_scheduled") == 1 and "step_failed" in types


def test_deterministic_step_failure_is_not_retried(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = approved_plan_run(client, team, login)
    broken = replace(
        fake_agents(), researcher=FlakyResearcher(StepFailed("research", "invalid output twice"))
    )
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), agents=broken) == "failed"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "FAILED" and detail["job"]["state"] == "FAILED"
    assert "invalid output twice" in detail["outcome_reason"]


class GreedyPlanner(FakePlanner):
    """Simulates a model that tries to grant itself an unapproved tool."""

    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]:
        call = super().plan(brief, version=version, feedback=feedback)
        tasks = [t.model_copy(update={"tools": ["web_search", "search_uploads"]}) for t in call.output.tasks]
        return AgentCall(call.output.model_copy(update={"tasks": tasks}), 1)


def test_planner_cannot_expand_tool_allowlist(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = start_run(client, login(team["analyst"]), team["workspace"])
    agents = replace(fake_agents(), planner=GreedyPlanner())
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), agents=agents) == "failed"
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "FAILED" and "disallowed tools" in detail["outcome_reason"]
    assert detail["plan"] is None, "a policy-violating plan is never stored"
