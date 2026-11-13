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
from app.workflow.errors import StepFailed, TransientError
from tests.conftest import LoggedIn
from tests.test_workflow import decide, start_run
from tests.test_workflow import team as team

KEY = "AIzaSy-secret-KEY9"


class Rejecting:
    """A provider that rejects every request, like Gemini with a bad key."""

    name, model = "google-gemini", "gemini-3.8-flash"

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
    assert detail["report"]["generation"]["fallback_from"] == "google-gemini/gemini-3.8-flash"
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
    responses: list[httpx.Response], seen: list[dict[str, Any]], model: str = "gemini-3.8-flash"
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
    )  # an optional setting rejected: plain retry on the same model
    result = gemini([bad, OK], seen).complete(system="S", user="U", json_output=True, max_output_tokens=50)
    assert result.text == "{}"
    assert "responseMimeType" in seen[0]["generationConfig"]
    assert seen[1]["generationConfig"] == {"maxOutputTokens": 65536}, "only the limit"
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
    llm = gemini([OK], seen, model=" models/Gemini-3.8-Flash ")
    assert llm.model == "gemini-3.8-flash" and llm._key == KEY


@pytest.mark.parametrize(
    ("stored", "used"),
    [
        ("gemini-2.5-flash", "gemini-4-hydrogen"),
        ("models/gemini-2.5-pro", "gemini-4-hydrogen"),
        ("gemini-3.0-flash", "gemini-4-hydrogen"),
        ("gemini-3.5-flash", "gemini-4-hydrogen"),
        ("gemini-3.8-flash", "gemini-3.8-flash"),
        ("gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
        ("", "gemini-4-hydrogen"),
    ],
)
def test_retired_model_ids_are_replaced(stored: str, used: str) -> None:
    assert normalize_model(stored) == used


def test_a_paid_only_model_on_a_free_key_moves_down_the_chain_in_the_same_call() -> None:
    seen: list[dict[str, Any]] = []
    urls: list[str] = []
    paid = httpx.Response(
        403,
        json={
            "error": {
                "status": "PERMISSION_DENIED",
                "message": "gemini-4-argon is not available on the free tier",
            }
        },
    )
    quota = httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}})
    gone = httpx.Response(404, json={"error": {"status": "NOT_FOUND", "message": "model not found"}})
    answered = httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4, "thoughtsTokenCount": 6},
        },
    )
    responses = [paid, quota, gone, answered]

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        urls.append(str(request.url))
        seen.append(json.loads(request.content))
        return responses.pop(0)

    llm = GeminiLlm(
        KEY,
        "gemini-4-argon",
        thinking_level="xhigh",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = llm.complete(system="S", user="U", json_output=True, max_output_tokens=50)
    assert [u.rsplit("/", 1)[1].split(":")[0] for u in urls] == [
        "gemini-4-argon",
        "gemini-4-hydrogen",
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
    ]
    assert [c["generationConfig"].get("thinkingConfig") for c in seen] == [
        {"thinkingLevel": "high"},  # Argon has no xhigh: the nearest level it offers
        {"thinkingLevel": "xhigh"},
        {"thinkingLevel": "high"},
        {"thinkingLevel": "high"},  # Flash-Lite offers medium and high
    ]
    assert all(c["generationConfig"]["maxOutputTokens"] == 65536 for c in seen)
    assert all("temperature" not in c["generationConfig"] for c in seen)
    assert result.usage.model == "gemini-3.5-flash-lite"
    assert result.usage.output_tokens == 10, "thinking tokens are billed as output"


def test_researchers_use_hydrogen_at_low_thinking() -> None:
    llm = GeminiLlm(KEY, "gemini-4-carbon", thinking_level="high")
    research = llm.with_role("research")
    assert (research.model, research.thinking_level) == ("gemini-4-hydrogen", "low")
    assert llm.with_role("planner") is llm
    flash = GeminiLlm(KEY, "gemini-3.8-flash").with_role("research")
    assert flash.model == "gemini-3.8-flash"
    assert llm.output_cap(1500) == 65536


def test_when_every_model_is_out_of_quota_the_worker_retries_later() -> None:
    quota = httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}})
    llm = GeminiLlm(
        KEY, "gemini-4-hydrogen", client=httpx.Client(transport=httpx.MockTransport(lambda _: quota))
    )
    with pytest.raises(TransientError, match=r"gemini-3\.5-flash-lite: HTTP 429 RESOURCE_EXHAUSTED"):
        llm.complete(system="S", user="U", json_output=False, max_output_tokens=10)


def test_an_overloaded_or_slow_model_hands_the_request_to_the_next_one() -> None:
    urls: list[str] = []
    answered = httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]}
    )
    script: list[Any] = [
        httpx.Response(503, json={"error": {"status": "UNAVAILABLE", "message": "The model is overloaded."}}),
        httpx.ReadTimeout("slow"),
        answered,
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url.path.rsplit("/", 1)[1].split(":")[0])
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    llm = GeminiLlm(KEY, "gemini-4-hydrogen", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = llm.complete(system="S", user="U", json_output=True, max_output_tokens=50)
    assert urls == ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert result.usage.model == "gemini-3.5-flash-lite"


def test_no_more_than_two_requests_per_key_are_in_flight() -> None:
    import threading
    import time

    active = 0
    peak = 0
    lock = threading.Lock()
    ok = httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]}
    )

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return ok

    llm = GeminiLlm(
        "slot-test-key", "gemini-4-hydrogen", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    call = {"system": "S", "user": "U", "json_output": False, "max_output_tokens": 5}
    threads = [threading.Thread(target=llm.complete, kwargs=call) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 2


class RateLimited:
    """Every model in the provider's chain is out of quota, every time."""

    name, model = "google-gemini", "gemini-4-hydrogen"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_: Any) -> LlmResult:
        self.calls += 1
        raise TransientError("every Gemini model was unavailable: gemini-4-hydrogen: HTTP 429 quota exceeded")


def test_a_run_never_fails_when_every_model_stays_rate_limited(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    settings = get_settings().model_copy(update={"agent_mode": "llm", "llm_fallback": True})
    llm = RateLimited()
    run_id = start_run(client, analyst, team["workspace"])
    assert process_one(settings, run_id=uuid.UUID(run_id), llm=llm) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    for _ in range(4):
        if client.get(f"/api/v1/runs/{run_id}").json()["state"] == "AWAITING_REPORT_APPROVAL":
            break
        process_one(settings, run_id=uuid.UUID(run_id), llm=llm)
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "AWAITING_REPORT_APPROVAL", detail.get("outcome_reason")
    timeline = client.get(f"/api/v1/runs/{run_id}/timeline").json()
    assert not [e for e in timeline if e["type"] == "retry_scheduled"], "no worker retries were needed"
    tasks = [e["payload"] for e in timeline if e["type"] == "task_completed"]
    assert tasks and all("HTTP 429" in t["fallback_reason"] for t in tasks)
    assert all(t["status"] == "succeeded" for t in tasks), "findings quote the collected passages"


def test_collected_returns_a_tasks_passages_from_the_database(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    from types import SimpleNamespace

    from app.db.session import get_sessionmaker
    from app.tools.research import RunResearchTools

    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    process_one(get_settings(), run_id=uuid.UUID(run_id))
    decide(client, analyst, run_id, "plan")
    process_one(get_settings(), run_id=uuid.UUID(run_id))
    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    task_id = evidence[0]["task_id"]
    ctx = SimpleNamespace(
        sm=get_sessionmaker(), run_id=uuid.UUID(run_id), brief=SimpleNamespace(source_policy=None)
    )
    found = RunResearchTools(ctx, task_id).collected()  # type: ignore[arg-type]
    assert {ref.evidence_id for ref, _ in found} == {
        e["evidence_id"] for e in evidence if e["task_id"] == task_id
    }
    assert all(title for _, title in found)
