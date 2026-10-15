"""M10: tracing with redaction, metrics, rate limits, circuit breaker, workspace usage."""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import RateLimitCounter, Role, RunJob, User, Workspace
from app.db.session import get_sessionmaker
from app.observability.tracing import LIBRARY_SAFE_KEYS, SAFE_KEYS, configure_tracing, safe_attributes, span
from app.providers.breaker import BreakerLlm, CircuitBreaker, reset_breakers
from app.providers.llm import LlmResult, LlmUsage
from app.workers.runner import process_one
from app.workflow.errors import TransientError
from tests.conftest import SAMPLE_BRIEF, LoggedIn
from tests.test_research_budgets import ResponderLlm
from tests.test_workflow import decide

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def tracing() -> None:
    # The global tracer provider can be installed once per process; the in-memory exporter
    # collects everything from here on and each test clears it first.
    configure_tracing(get_settings(), "aos-test", exporter=EXPORTER)


@pytest.fixture
def team(
    make_user: Callable[..., User], make_workspace: Callable[..., Workspace], checkpointer_ready: None
) -> dict[str, Any]:
    analyst, reviewer = make_user("Ana"), make_user("Rev")
    workspace = make_workspace("Team", {analyst: Role.ANALYST, reviewer: Role.REVIEWER})
    return {"analyst": analyst, "reviewer": reviewer, "workspace": workspace}


@pytest.fixture
def settings_override(client: TestClient) -> Iterator[Callable[..., Settings]]:
    def apply(**changes: Any) -> Settings:
        settings = get_settings().model_copy(update=changes)
        client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
        return settings

    yield apply
    client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


SECRET_TOPIC = "Vendor sk-live-ABCDEFGHIJKLMNOPQRSTUVWX comparison"


def create_run(client: TestClient, session: LoggedIn, workspace: Workspace, **brief: Any) -> Any:
    return client.post(
        "/api/v1/runs",
        json={"workspace_id": str(workspace.id), "brief": {**SAMPLE_BRIEF, **brief}},
        headers={**session.headers, "Idempotency-Key": uuid.uuid4().hex},
    )


# --- Tracing ---------------------------------------------------------------------------------


def test_workflow_is_traced_end_to_end_without_content_or_secrets(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    EXPORTER.clear()
    analyst = login(team["analyst"])
    response = create_run(client, analyst, team["workspace"], topic=SECRET_TOPIC)
    run_id = response.json()["id"]
    llm = ResponderLlm()
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), llm=llm) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), llm=llm) == "waiting_report"

    spans: list[ReadableSpan] = list(EXPORTER.get_finished_spans())
    names = {s.name for s in spans}
    assert {"POST /api/v1/runs", "worker.pass", "step.planner", "step.research", "research.task"} <= names
    assert {"llm.call", "search.call", "step.writer", "step.reviewer"} <= names

    llm_calls = [s for s in spans if s.name == "llm.call"]
    assert {s.attributes["aos.step"] for s in llm_calls} >= {"planner", "research", "writer", "reviewer"}
    assert all(int(s.attributes["aos.input_tokens"]) > 0 for s in llm_calls)

    by_id = {s.context.span_id: s for s in spans}
    task = next(s for s in spans if s.name == "research.task")
    assert task.parent is not None and by_id[task.parent.span_id].name == "step.research", (
        "research threads stay inside the step's trace"
    )
    plan_wait = next(s for s in spans if s.name == "step.await_plan")
    assert plan_wait.status.is_ok and plan_wait.attributes.get("aos.outcome") == "interrupted"

    for s in spans:
        for key, value in (s.attributes or {}).items():
            assert key in SAFE_KEYS | LIBRARY_SAFE_KEYS, f"{s.name} carries non-allowlisted attribute {key}"
            assert "sk-live" not in str(value) and "Vendor" not in str(value), "no content or secrets"
        assert not s.events, "no events (exception messages) are exported"


def test_span_attributes_are_allowlisted_redacted_and_truncated() -> None:
    clean = safe_attributes(
        {
            "aos.model": "gpt-x",
            "aos.step": "x" * 500,
            "aos.provider": "Bearer abcdefghijklmnopqrstuvwxyz123456",
            "prompt": "the full prompt",
            "aos.input_tokens": 12,
        }
    )
    assert "prompt" not in clean and clean["aos.input_tokens"] == 12
    assert len(str(clean["aos.step"])) == 200
    assert "abcdefghijklmnopqrstuvwxyz123456" not in str(clean["aos.provider"])


def test_errors_are_recorded_by_type_only() -> None:
    EXPORTER.clear()
    with pytest.raises(ValueError), span("boom", step="planner"):
        raise ValueError("secret detail sk-live-ABCDEFGHIJKLMNOPQRSTUVWX")
    (finished,) = EXPORTER.get_finished_spans()
    assert finished.attributes["error.type"] == "ValueError" and not finished.status.is_ok
    assert not finished.events, "no exception message or stack trace is exported"


# --- Metrics ---------------------------------------------------------------------------------


def test_metrics_expose_workflow_and_http_state(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = create_run(client, analyst, team["workspace"]).json()["id"]
    assert process_one(get_settings(), run_id=uuid.UUID(run_id)) == "waiting_plan"
    body = client.get("/metrics").text
    assert 'aos_runs{state="AWAITING_PLAN_APPROVAL"} 1' in body
    assert 'aos_approvals_waiting{kind="plan"} 1' in body
    assert 'aos_http_requests_total{method="POST",route="/api/v1/runs",status="201"}' in body
    assert "aos_http_request_duration_seconds_bucket" in body and "aos_jobs_expired_leases 0" in body
    assert "Ana" not in body and run_id not in body, "no names or ids in metrics"


def test_metrics_require_the_token_when_configured_and_are_hidden_in_prod(
    client: TestClient, settings_override: Callable[..., Settings], db: Session
) -> None:
    settings_override(metrics_token=SecretStr("scrape-token-123"))
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"}).status_code == 200
    settings_override(env="prod", metrics_token=None)
    assert client.get("/metrics").status_code == 404


# --- Rate limits -----------------------------------------------------------------------------


def test_run_creation_is_rate_limited_per_user_with_retry_after(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    settings_override: Callable[..., Settings],
) -> None:
    settings_override(rate_run_create_per_user_hour=2)
    analyst = login(team["analyst"])
    assert [create_run(client, analyst, team["workspace"]).status_code for _ in range(2)] == [201, 201]
    limited = create_run(client, analyst, team["workspace"])
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(limited.headers["retry-after"]) <= 3600


def test_outsiders_cannot_exhaust_a_workspace_quota(
    client: TestClient,
    team: dict[str, Any],
    make_user: Callable[..., User],
    login: Callable[[User], LoggedIn],
    settings_override: Callable[..., Settings],
    db: Session,
) -> None:
    settings_override(rate_run_create_per_workspace_hour=1)
    outsider = login(make_user("Mallory"))
    for _ in range(3):
        assert create_run(client, outsider, team["workspace"]).status_code == 404
    analyst = login(team["analyst"])
    assert create_run(client, analyst, team["workspace"]).status_code == 201
    assert create_run(client, analyst, team["workspace"]).status_code == 429
    keys = db.scalars(select(RateLimitCounter.key)).all()
    workspace_count = db.scalar(
        select(RateLimitCounter.count).where(RateLimitCounter.key == f"run_create:ws:{team['workspace'].id}")
    )
    assert workspace_count == 2, "only the member's two attempts counted against the workspace"
    assert f"run_create:user:{outsider.user.id}" in keys, "outsiders spend only their own quota"


def test_login_is_rate_limited_per_client_and_keys_hold_no_raw_ip(
    client: TestClient, settings_override: Callable[..., Settings], db: Session
) -> None:
    settings_override(rate_login_per_ip_5min=2)
    codes = [client.get("/api/v1/auth/login", follow_redirects=False).status_code for _ in range(3)]
    assert codes[:2] != [429, 429] and codes[2] == 429
    keys = db.scalars(select(RateLimitCounter.key).where(RateLimitCounter.key.like("login:%"))).all()
    assert keys and all("testclient" not in k for k in keys)


# --- Circuit breaker -------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_breaker_opens_fails_fast_then_half_opens_and_closes() -> None:
    clock = Clock()
    breaker = CircuitBreaker("llm:test", threshold=2, cooldown=30, clock=clock)
    breaker.record_failure()
    breaker.before_call()
    breaker.record_failure()
    assert breaker.state == "open"
    with pytest.raises(TransientError) as raised:
        breaker.before_call()
    assert raised.value.retry_after == 30
    clock.now = 31
    assert breaker.state == "half_open"
    breaker.before_call()  # the single trial call
    with pytest.raises(TransientError):
        breaker.before_call()  # concurrent callers keep failing fast during the trial
    breaker.record_failure()
    assert breaker.state == "open", "a failed trial re-opens the circuit"
    clock.now = 62
    breaker.before_call()
    breaker.record_success()
    assert breaker.state == "closed" and breaker.failures == 0


class DownLlm:
    name, model = "down", "down-1"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
        self.calls += 1
        raise TransientError("provider returned 503")


def test_provider_outage_degrades_to_backoff_without_calling_or_reserving(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    reset_breakers()
    analyst = login(team["analyst"])
    run_id = create_run(client, analyst, team["workspace"]).json()["id"]
    settings = get_settings().model_copy(
        update={"breaker_failure_threshold": 1, "breaker_cooldown_seconds": 600}
    )
    down = DownLlm()
    assert process_one(settings, run_id=uuid.UUID(run_id), llm=down) == "retry"
    assert down.calls == 1
    with get_sessionmaker()() as s:
        s.execute(update(RunJob).where(RunJob.run_id == uuid.UUID(run_id)).values(available_at=func.now()))
        s.commit()
    reserved_before = db.scalar(
        text("SELECT count(*) FROM budget_reservations WHERE run_id = :r"), {"r": run_id}
    )
    assert process_one(settings, run_id=uuid.UUID(run_id), llm=down) == "retry"
    assert down.calls == 1, "an open circuit does not call the provider"
    reserved_after = db.scalar(
        text("SELECT count(*) FROM budget_reservations WHERE run_id = :r"), {"r": run_id}
    )
    assert reserved_after == reserved_before, "an open circuit reserves no budget"
    retries = [
        e for e in client.get(f"/api/v1/runs/{run_id}/timeline").json() if e["type"] == "retry_scheduled"
    ]
    assert "circuit open" in retries[-1]["payload"]["reason"]
    reset_breakers()


def test_breaker_wrapper_counts_only_transient_failures() -> None:
    reset_breakers()

    class Flaky:
        name, model = "flaky", "f-1"

        def __init__(self) -> None:
            self.mode = "bad_output"

        def complete(self, *, system: str, user: str, json_output: bool, max_output_tokens: int) -> LlmResult:
            if self.mode == "transient":
                raise TransientError("timeout")
            if self.mode == "bad_output":
                raise ValueError("not a transient failure")
            return LlmResult("{}", LlmUsage("flaky", "f-1", 1, 1))

    inner = Flaky()
    wrapped = BreakerLlm(inner, get_settings().model_copy(update={"breaker_failure_threshold": 1}))
    with pytest.raises(ValueError):
        wrapped.complete(system="s", user="u", json_output=True, max_output_tokens=5)
    assert wrapped.breaker.state == "closed"
    inner.mode = "transient"
    with pytest.raises(TransientError):
        wrapped.complete(system="s", user="u", json_output=True, max_output_tokens=5)
    assert wrapped.breaker.state == "open"
    reset_breakers()


# --- Usage -----------------------------------------------------------------------------------


def test_workspace_usage_aggregates_estimated_spend(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = create_run(client, analyst, team["workspace"], topic="Usage run").json()["id"]
    llm = ResponderLlm()
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), llm=llm) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), llm=llm) == "waiting_report"

    usage = client.get(f"/api/v1/workspaces/{team['workspace'].id}/usage?days=7").json()
    assert usage["days"] == 7 and usage["totals"]["runs"] == 1 and usage["totals"]["calls"] >= 5
    assert float(usage["totals"]["committed"]) > 0 and usage["totals"]["llm_input_tokens"] > 0
    steps = {(s["step"], s["kind"]) for s in usage["by_step"]}
    assert {("planner", "llm"), ("research", "llm"), ("writer", "llm"), ("reviewer", "llm")} <= steps
    assert usage["top_runs"][0]["run_id"] == run_id and usage["top_runs"][0]["topic"] == "Usage run"
    assert len(usage["by_day"]) == 1 and "estimated" in usage["note"].lower()

    reviewer = login(team["reviewer"])
    assert (
        client.get(f"/api/v1/workspaces/{team['workspace'].id}/usage", headers=reviewer.headers).status_code
        == 403
    )
