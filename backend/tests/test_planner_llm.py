"""M6: LLM adapter, bounded structured repair, LLM planner, plan edits, approval expiry."""

import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.agents.fake import fake_agents
from app.agents.llm_planner import LlmPlanner
from app.agents.prompts import PLANNER_VERSION
from app.agents.structured import call_structured
from app.config import Settings, get_settings
from app.contracts import Brief, Plan
from app.db.models import Role, RunJob, User, Workspace
from app.db.session import get_sessionmaker
from app.providers.llm import OpenAICompatibleLlm, ScriptedLlm
from app.workers.maintenance import expire_overdue_waits
from app.workers.runner import process_one
from app.workflow.errors import StepFailed, TransientError
from tests.conftest import SAMPLE_BRIEF, LoggedIn
from tests.test_workflow import decide, start_run

BRIEF = Brief.model_validate(SAMPLE_BRIEF)


def plan_json(**overrides: Any) -> str:
    plan: dict[str, Any] = {
        "plan_version": 99,  # the server assigns versions; this must be overridden
        "tasks": [
            {
                "task_id": "hosting",
                "question": "Which options can be self-hosted?",
                "tools": ["web_search", "fetch_url"],
                "expected_evidence": "Official deployment docs",
                "section_ids": ["findings"],
            },
            {
                "task_id": "compare",
                "question": "How do they compare?",
                "depends_on": ["hosting"],
                "tools": ["web_search"],
                "expected_evidence": "Comparisons",
                "section_ids": ["summary"],
            },
        ],
        "outline": [
            {"section_id": "summary", "title": "Summary", "purpose": "Answer"},
            {"section_id": "findings", "title": "Findings", "purpose": "Evidence"},
        ],
        "source_strategy": "Vendor documentation first.",
        "assumptions": ["Small team, no dedicated ops staff"],
    }
    plan.update(overrides)
    return json.dumps(plan)


# --- structured output ------------------------------------------------------------------


def test_planner_produces_validated_plan_with_provenance() -> None:
    llm = ScriptedLlm([f"```json\n{plan_json()}\n```"])
    call = LlmPlanner(llm).plan(BRIEF, version=1, feedback=None)
    assert [t.task_id for t in call.output.tasks] == ["hosting", "compare"]
    assert call.attempts == 1
    assert (
        call.generation["prompt_version"] == PLANNER_VERSION and call.generation["model"] == "scripted-model"
    )
    system, user = llm.calls[0]["system"], llm.calls[0]["user"]
    assert "fetch_url, web_search" in system and f"at most {BRIEF.limits.max_tasks} tasks" in system
    assert BRIEF.topic in user and '"properties"' in user, "brief and JSON schema are in the prompt"
    assert llm.calls[0]["json_output"] is True


def test_one_repair_then_success_without_echoing_bad_output() -> None:
    llm = ScriptedLlm(["Sure! Here is a plan: TOP-SECRET-PROSE", plan_json()])
    call = LlmPlanner(llm).plan(BRIEF, version=1, feedback="Focus on SSO")
    assert call.attempts == 2
    repair_prompt = llm.calls[1]["user"]
    assert "rejected by the validator" in repair_prompt and "TOP-SECRET-PROSE" not in repair_prompt
    assert "Focus on SSO" in llm.calls[0]["user"]


def test_policy_violations_get_the_single_repair_then_fail_visibly() -> None:
    greedy = plan_json(
        tasks=[
            {
                "task_id": "t1",
                "question": "q",
                "tools": ["search_uploads"],
                "expected_evidence": "e",
                "section_ids": ["summary"],
            }
        ]
    )
    llm = ScriptedLlm([greedy, greedy])
    with pytest.raises(StepFailed) as info:
        LlmPlanner(llm).plan(BRIEF, version=1, feedback=None)
    assert "after 2 attempts" in info.value.reason and "disallowed tools" in info.value.reason
    assert len(llm.calls) == 2, "exactly one repair"


def test_cyclic_plan_is_rejected_by_the_contract() -> None:
    cyclic = plan_json(
        tasks=[
            {
                "task_id": "a",
                "question": "q",
                "depends_on": ["b"],
                "tools": ["web_search"],
                "expected_evidence": "e",
                "section_ids": ["summary"],
            },
            {
                "task_id": "b",
                "question": "q",
                "depends_on": ["a"],
                "tools": ["web_search"],
                "expected_evidence": "e",
                "section_ids": ["summary"],
            },
        ]
    )
    with pytest.raises(StepFailed) as info:
        call_structured(
            ScriptedLlm([cyclic, cyclic]), Plan, step="planner", system="s", user="u", max_output_tokens=10
        )
    assert "dependency cycle" in info.value.reason


# --- OpenAI-compatible adapter ---------------------------------------------------------


def adapter(handler: Callable[[httpx2.Request], httpx2.Response]) -> OpenAICompatibleLlm:
    client = openai.OpenAI(
        api_key="sk-test-not-real",
        base_url="https://llm.test/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenAICompatibleLlm(Settings(llm_model="test-model", env="test"), client=client)


def completion(text: str) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model-2026",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }


def test_adapter_request_and_usage_mapping() -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.update(json.loads(request.content))
        sent["auth"] = request.headers["authorization"]
        return httpx2.Response(200, json=completion('{"ok": true}'))

    result = adapter(handler).complete(system="sys", user="usr", json_output=True, max_output_tokens=50)
    assert result.text == '{"ok": true}'
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.model) == (
        120,
        30,
        "test-model-2026",
    )
    assert sent["model"] == "test-model" and sent["response_format"] == {"type": "json_object"}
    assert sent["seed"] == 7 and sent["max_tokens"] == 50
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert sent["auth"] == "Bearer sk-test-not-real"


@pytest.mark.parametrize(
    ("status", "transient"), [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)]
)
def test_adapter_error_classification(status: int, transient: bool) -> None:
    llm = adapter(
        lambda r: httpx2.Response(status, headers={"retry-after": "3"}, json={"error": {"message": "x"}})
    )
    expected = TransientError if transient else StepFailed
    with pytest.raises(expected) as info:
        llm.complete(system="s", user="u", json_output=True, max_output_tokens=5)
    if status == 429:
        assert info.value.retry_after == 3.0  # type: ignore[union-attr]


def test_adapter_network_failure_is_transient() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with pytest.raises(TransientError):
        adapter(boom).complete(system="s", user="u", json_output=True, max_output_tokens=5)


# --- workflow integration ----------------------------------------------------------------


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


def test_llm_planned_run_records_model_provenance(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = start_run(client, login(team["analyst"]), team["workspace"])
    agents = replace(fake_agents(), planner=LlmPlanner(ScriptedLlm([plan_json()])))
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), agents=agents) == "waiting_plan"
    plan = client.get(f"/api/v1/runs/{run_id}").json()["plan"]
    assert plan["version"] == 1 and plan["body"]["plan_version"] == 1, "server-assigned version"
    assert plan["generation"]["prompt_version"] == PLANNER_VERSION and plan["author"] == "agent"
    event = next(
        e for e in client.get(f"/api/v1/runs/{run_id}/timeline").json() if e["type"] == "plan_proposed"
    )
    assert event["payload"]["model"] == "scripted-model" and event["payload"]["input_tokens"] > 0
    assert "prompt" not in json.dumps(event["payload"]).replace("prompt_version", ""), (
        "no prompt text in events"
    )


def test_plan_edit_creates_new_version_that_must_be_approved(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    process_one(get_settings(), run_id=uuid.UUID(run_id))
    v1 = client.get(f"/api/v1/runs/{run_id}").json()["plan"]

    edited = json.loads(plan_json())
    edited["tasks"] = edited["tasks"][:1]
    response = client.put(
        f"/api/v1/runs/{run_id}/plan", json={"base_version": 1, "plan": edited}, headers=analyst.headers
    )
    assert response.status_code == 200, response.text
    v2 = response.json()
    assert v2["version"] == 2 and v2["author"] == "user" and v2["generation"]["edited_from"] == 1

    stale = client.put(
        f"/api/v1/runs/{run_id}/plan", json={"base_version": 1, "plan": edited}, headers=analyst.headers
    )
    assert stale.status_code == 409
    old_approval = client.post(
        f"/api/v1/runs/{run_id}/plan-decisions",
        json={"version": 1, "digest": v1["digest"], "decision": "approve"},
        headers=analyst.headers,
    )
    assert old_approval.status_code == 409, "editing invalidates the earlier version"

    assert decide(client, analyst, run_id, "plan").status_code == 201
    assert process_one(get_settings(), run_id=uuid.UUID(run_id)) == "waiting_report"
    completed = [
        e["payload"]["task_id"]
        for e in client.get(f"/api/v1/runs/{run_id}/timeline").json()
        if e["type"] == "task_completed"
    ]
    assert completed == ["hosting"], "research follows the approved edited plan"


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        (lambda p: p["tasks"][0].update({"depends_on": ["compare"]}), 422),  # cycle
        (lambda p: p["tasks"][0].update({"tools": ["search_uploads"]}), 422),  # not allowed by the brief
        (lambda p: p.update({"tasks": []}), 422),
    ],
    ids=["cycle", "disallowed-tool", "empty"],
)
def test_invalid_plan_edits_are_rejected(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    mutate: Callable[[dict[str, Any]], None],
    status: int,
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    process_one(get_settings(), run_id=uuid.UUID(run_id))
    plan = json.loads(plan_json())
    mutate(plan)
    response = client.put(
        f"/api/v1/runs/{run_id}/plan", json={"base_version": 1, "plan": plan}, headers=analyst.headers
    )
    assert response.status_code == status


def test_reviewers_cannot_edit_plans(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = start_run(client, login(team["analyst"]), team["workspace"])
    process_one(get_settings(), run_id=uuid.UUID(run_id))
    response = client.put(
        f"/api/v1/runs/{run_id}/plan",
        json={"base_version": 1, "plan": json.loads(plan_json())},
        headers=login(team["reviewer"]).headers,
    )
    assert response.status_code == 403


def test_overdue_approval_waits_expire_and_reject_late_decisions(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    process_one(get_settings(), run_id=uuid.UUID(run_id))
    pending = client.get(f"/api/v1/runs/{run_id}").json()["pending_decision"]
    with get_sessionmaker()() as s:
        s.execute(
            update(RunJob)
            .where(RunJob.run_id == uuid.UUID(run_id))
            .values(wait_deadline_at=text("now() - interval '1 minute'"))
        )
        s.commit()
    assert expire_overdue_waits(get_sessionmaker()) == 1
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "EXPIRED" and "No plan decision" in detail["outcome_reason"]
    late = client.post(
        f"/api/v1/runs/{run_id}/plan-decisions",
        json={"version": pending["version"], "digest": pending["digest"], "decision": "approve"},
        headers=analyst.headers,
    )
    assert late.status_code == 409
    assert expire_overdue_waits(get_sessionmaker()) == 0
