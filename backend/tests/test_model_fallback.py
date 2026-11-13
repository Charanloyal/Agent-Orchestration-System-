"""A live run never dies on a permanent model error (ADR 0030): the failing step is done by the
deterministic agent and labelled; Gemini errors carry Google's own message, never the key."""

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import User
from app.providers.gemini import GeminiLlm, normalize_model
from app.providers.llm import LlmResult
from app.workers.runner import process_one
from app.workflow.errors import StepFailed
from tests.conftest import LoggedIn
from tests.test_workflow import decide, start_run
from tests.test_workflow import team as team

KEY = "AIzaSy-secret-KEY9"


class Rejecting:
    """A provider that rejects every request, like Gemini with a bad key."""

    name, model = "google-gemini", "gemini-2.5-flash"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_: Any) -> LlmResult:
        self.calls += 1
        raise StepFailed(
            "model", "model provider rejected the request (HTTP 400: INVALID_ARGUMENT: API key not valid)"
        )


def drive(run_id: str, llm: Rejecting, settings: Any) -> str:
    return process_one(settings, run_id=uuid.UUID(run_id), llm=llm)


def test_a_rejecting_model_falls_back_step_by_step_and_the_run_completes(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    analyst = login(team["analyst"])
    settings = get_settings().model_copy(update={"agent_mode": "llm", "llm_fallback": True})
    llm = Rejecting()
    run_id = start_run(client, analyst, team["workspace"])
    assert drive(run_id, llm, settings) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    for _ in range(6):
        if client.get(f"/api/v1/runs/{run_id}").json()["state"] == "AWAITING_REPORT_APPROVAL":
            break
        drive(run_id, llm, settings)
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "AWAITING_REPORT_APPROVAL", detail.get("outcome_reason")
    assert llm.calls >= 4, "every step tried the model first"
    assert detail["plan"]["generation"]["fallback_reason"].endswith("API key not valid)")
    assert detail["report"]["generation"]["fallback_from"] == "google-gemini/gemini-2.5-flash"
    timeline = client.get(f"/api/v1/runs/{run_id}/timeline").json()
    proposed = next(e for e in timeline if e["type"] == "plan_proposed")
    assert "API key not valid" in proposed["payload"]["fallback_reason"]
    assert decide(client, login(team["reviewer"]), run_id, "report").status_code == 201


def test_without_fallback_the_run_fails_with_the_providers_reason(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    settings = get_settings().model_copy(update={"agent_mode": "llm", "llm_fallback": False})
    run_id = start_run(client, login(team["analyst"]), team["workspace"])
    drive(run_id, Rejecting(), settings)
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "FAILED"
    assert "API key not valid" in detail["outcome_reason"]


def gemini(
    responses: list[httpx.Response], seen: list[dict[str, Any]], model: str = "gemini-2.5-flash"
) -> GeminiLlm:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return responses.pop(0)

    return GeminiLlm(f"  {KEY}\n", model, client=httpx.Client(transport=httpx.MockTransport(handler)))


OK = httpx.Response(
    200,
    json={
        "candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}],
        "usageMetadata": {},
    },
)


def test_a_rejected_optional_setting_is_retried_once_with_plain_generation() -> None:
    seen: list[dict[str, Any]] = []
    bad = httpx.Response(
        400, json={"error": {"status": "INVALID_ARGUMENT", "message": "Unknown name thinkingConfig"}}
    )
    result = gemini([bad, OK], seen).complete(system="S", user="U", json_output=True, max_output_tokens=50)
    assert result.text == "{}"
    assert "responseMimeType" in seen[0]["generationConfig"]
    assert seen[1]["generationConfig"] == {"maxOutputTokens": 50}
    assert seen[1]["systemInstruction"] == {"parts": [{"text": "S"}]}
    assert [c["role"] for c in seen[1]["contents"]] == ["user"]


def test_a_bad_key_is_not_retried_and_the_reason_is_googles_without_the_key() -> None:
    seen: list[dict[str, Any]] = []
    bad = httpx.Response(
        400,
        json={
            "error": {"status": "INVALID_ARGUMENT", "message": f"API key not valid: {KEY}. Pass a valid key."}
        },
    )
    with pytest.raises(StepFailed) as raised:
        gemini([bad], seen).complete(system="S", user="U", json_output=True, max_output_tokens=50)
    assert len(seen) == 1
    assert "HTTP 400: INVALID_ARGUMENT: API key not valid: ***" in raised.value.reason
    assert KEY not in raised.value.reason


def test_the_key_and_model_are_normalised() -> None:
    seen: list[dict[str, Any]] = []
    llm = gemini([OK], seen, model=" models/Gemini-2.5-Flash ")
    assert llm.model == "gemini-2.5-flash" and llm._key == KEY
    assert normalize_model("gemini-2.0-flash") == "gemini-2.0-flash"
