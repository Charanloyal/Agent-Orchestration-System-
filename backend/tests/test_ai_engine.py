"""A workspace's own model engine (ADR 0029): saved by admins, encrypted, never returned, used by
runs and the style studio; the native Gemini adapter; the fallback when a model misbehaves."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Role, User, Workspace, WorkspaceAiConfig
from app.providers.gemini import GeminiLlm
from app.providers.llm import LlmResult, LlmUsage, OpenAICompatibleLlm, ScriptedLlm
from app.services import ai_engine
from app.workflow.errors import StepFailed, TransientError
from tests.conftest import LoggedIn
from tests.test_style import MARKDOWN

KEY = "AIzaSy-test-key-WXYZ"


@pytest.fixture
def team(make_user: Callable[..., User], make_workspace: Callable[..., Workspace]) -> dict[str, Any]:
    admin, analyst = make_user("Adm"), make_user("Ana")
    home = make_workspace("Home", {admin: Role.ADMIN, analyst: Role.ANALYST})
    return {"admin": admin, "analyst": analyst, "home": home}


def url(workspace: Workspace, tail: str = "") -> str:
    return f"/api/v1/workspaces/{workspace.id}/ai-config{tail}"


def test_admin_saves_a_key_that_is_encrypted_and_never_returned(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    admin = login(team["admin"])
    assert client.get(url(team["home"]), headers=admin.headers).json()["source"] == "demo"
    saved = client.put(
        url(team["home"]),
        json={"provider": "gemini", "model": "gemini-2.5-flash", "api_key": f"  {KEY}  "},
        headers=admin.headers,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["source"], body["live"], body["model"], body["key_hint"]) == (
        "workspace",
        True,
        "gemini-2.5-flash",
        "WXYZ",
    )
    assert body["label"] == "Google Gemini · gemini-2.5-flash"
    assert KEY not in saved.text
    row = db.get(WorkspaceAiConfig, team["home"].id)
    assert row is not None and KEY not in row.key_ciphertext
    assert ai_engine.decrypt_key(get_settings(), row.key_ciphertext) == KEY

    # Changing only the model keeps the key.
    changed = client.put(
        url(team["home"]), json={"provider": "gemini", "model": "gemini-2.5-pro"}, headers=admin.headers
    )
    assert changed.json()["model"] == "gemini-2.5-pro" and changed.json()["key_hint"] == "WXYZ"
    db.expire_all()
    llm = ai_engine.workspace_llm(db, get_settings(), team["home"].id)
    assert isinstance(llm, GeminiLlm) and llm.model == "gemini-2.5-pro"

    assert client.delete(url(team["home"]), headers=admin.headers).status_code == 204
    assert client.get(url(team["home"]), headers=admin.headers).json()["source"] == "demo"


def test_members_see_the_engine_but_only_admins_change_it(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    assert client.get(url(team["home"]), headers=analyst.headers).status_code == 200
    body = {"provider": "groq", "model": "llama-3.3-70b-versatile", "api_key": "gsk_x"}
    assert client.put(url(team["home"]), json=body, headers=analyst.headers).status_code == 403
    assert client.post(url(team["home"], "/test"), json={}, headers=analyst.headers).status_code == 403


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"provider": "gemini", "model": "gpt-4o"}, 422),  # model not offered by the provider
        ({"provider": "groq", "model": "llama-3.3-70b-versatile"}, 422),  # first save needs a key
        ({"provider": "gemini", "model": "gemini-2.5-flash", "api_key": "   "}, 422),
    ],
)
def test_invalid_engine_settings_are_refused(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    body: dict[str, Any],
    status: int,
) -> None:
    admin = login(team["admin"])
    assert client.put(url(team["home"]), json=body, headers=admin.headers).status_code == status


def test_production_needs_a_secrets_key_to_store_model_keys() -> None:
    prod = Settings(_env_file=None, env="test")  # type: ignore[call-arg]
    token = ai_engine.encrypt_key(prod, "k")
    assert ai_engine.decrypt_key(prod, token) == "k"
    unsafe = prod.model_copy(update={"env": "prod", "secrets_key": None})
    with pytest.raises(ai_engine.SecretsUnavailable):
        ai_engine.encrypt_key(unsafe, "k")
    assert ai_engine.decrypt_key(unsafe, token) is None, "an unreadable key falls back, never crashes"


def test_the_live_test_reports_latency_without_saving(
    client: TestClient,
    db: Session,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[tuple[str, str, str]] = []

    def fake_build(settings: Settings, provider: str, model: str, api_key: str) -> ScriptedLlm:
        built.append((provider, model, api_key))
        return ScriptedLlm(["ready"])

    monkeypatch.setattr(ai_engine, "build_llm", fake_build)
    admin = login(team["admin"])
    response = client.post(
        url(team["home"], "/test"), json={"provider": "gemini", "api_key": KEY}, headers=admin.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["latency_ms"] >= 0 and body["detail"] == "ready"
    assert built == [("gemini", "gemini-2.5-flash", KEY)]
    assert db.get(WorkspaceAiConfig, team["home"].id) is None, "testing saves nothing"
    nothing = client.post(url(team["home"], "/test"), json={}, headers=admin.headers)
    assert nothing.status_code == 422


def test_ping_reports_a_provider_failure_without_raising() -> None:
    class Broken(ScriptedLlm):
        def complete(self, **_: Any) -> LlmResult:
            raise StepFailed("model", "model provider rejected the request (HTTP 400)")

    result = ai_engine.ping(Broken([]))
    assert not result.ok and "HTTP 400" in result.detail


def gemini_with(
    handler: Callable[[httpx.Request], httpx.Response], model: str = "gemini-2.5-flash"
) -> GeminiLlm:
    return GeminiLlm(KEY, model, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_gemini_calls_generate_content_with_the_key_in_a_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5},
                "modelVersion": "gemini-2.5-flash",
                "responseId": "r1",
            },
        )

    result = gemini_with(handler).complete(system="S", user="U", json_output=True, max_output_tokens=100)
    request = seen[0]
    assert str(request.url).endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert KEY not in str(request.url) and request.headers["x-goog-api-key"] == KEY
    sent = json.loads(request.content)
    assert sent["systemInstruction"]["parts"][0]["text"] == "S"
    assert sent["contents"][0]["parts"][0]["text"] == "U"
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert sent["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert result.text == '{"ok": true}'
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.provider) == (
        12,
        5,
        "google-gemini",
    )


@pytest.mark.parametrize(
    ("status", "error"), [(429, TransientError), (503, TransientError), (400, StepFailed)]
)
def test_gemini_errors_are_classified(status: int, error: type[Exception]) -> None:
    llm = gemini_with(lambda _: httpx.Response(status, json={"error": {"message": f"bad {KEY}"}}))
    with pytest.raises(error) as raised:
        llm.complete(system="S", user="U", json_output=False, max_output_tokens=10)
    assert KEY not in str(raised.value)


def test_groq_and_openai_use_the_openai_compatible_client() -> None:
    llm = ai_engine.build_llm(get_settings(), "groq", "llama-3.3-70b-versatile", "gsk_test")
    assert isinstance(llm, OpenAICompatibleLlm) and llm.model == "llama-3.3-70b-versatile"
    assert str(llm._client.base_url).startswith("https://api.groq.com/openai/v1")


def style_post(client: TestClient, session: LoggedIn, workspace: Workspace, text: str) -> Any:
    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/style/rewrite",
        json={"text": text, "persona": "journalist"},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_style_studio_uses_the_model_and_keeps_its_rewrite_when_facts_survive(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = MARKDOWN.replace("India is building its own compute", "India builds its own compute")
    monkeypatch.setattr(ai_engine, "engine_llm", lambda *_: ScriptedLlm([good]))
    body = style_post(client, login(team["analyst"]), team["home"], MARKDOWN)
    assert body["engine"] == {"kind": "model", "note": "rewritten by scripted-model"}
    assert "India builds its own compute" in body["rewritten"]
    assert body["fact_lock"]["missing"] == []
    assert body["score_after"]["total"] >= body["score_before"]["total"]


def test_style_studio_rejects_a_model_rewrite_that_changes_a_fact(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = MARKDOWN.replace("40%", "45%")
    scripted = ScriptedLlm([bad, bad])
    monkeypatch.setattr(ai_engine, "engine_llm", lambda *_: scripted)
    body = style_post(client, login(team["analyst"]), team["home"], MARKDOWN)
    assert body["engine"]["kind"] == "rules" and "40%" in body["engine"]["note"]
    assert "40%" in body["rewritten"] and "45%" not in body["rewritten"]
    assert len(scripted.calls) == 2, "one correction round, then the rules"
    assert "rejected because it changed or dropped: 40%" in scripted.calls[1]["user"]


def test_style_score_follows_its_published_formula() -> None:
    from app.services.style import analyze, fact_lock, rewrite, style_score

    text = MARKDOWN
    after = rewrite(text).text
    before_score = style_score(analyze(text))
    after_score = style_score(analyze(after), fact_lock(text, after))
    report = analyze(after)
    expected = 100 * (
        0.3 * min(report.sentence_length_cv / 0.6, 1)
        + 0.2 * max(0, min((report.vocabulary_mattr - 0.5) / 0.4, 1))
        + 0.3 * max(0, 1 - report.stock_phrases_per_1000_words / 20)
        + 0.2
    )
    assert after_score.total == pytest.approx(expected, abs=0.1)
    assert after_score.total > before_score.total


def test_usage_shape_is_plain() -> None:
    assert LlmUsage("p", "m", 1, 2).model == "m"
