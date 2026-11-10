"""M12/M13: production safety, sign-in allowlist, request limits, readiness, single-origin
SPA serving, run deletion, retention, append-only audit log, worker DB-outage resilience."""

import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AuditEvent, ReportExport, Role, Run, Upload, User, Workspace
from app.db.session import get_sessionmaker
from app.main import app, create_app
from app.services.retention import sweep
from app.storage import get_object_store
from app.workers import runner
from tests.conftest import LoggedIn
from tests.test_auth_oidc import sign_in_via_dev_issuer
from tests.test_workflow import decide, start_run, work

SAFE_PROD: dict[str, Any] = {
    "env": "prod",
    "database_url": "postgresql://u:p@db.internal:5432/aos",
    "cookie_secure": True,
    "oidc_issuer": "https://login.example.org",
    "oidc_client_id": "aos-pilot",
    "public_url": "https://aos.example.org",
    "allowed_email_domains": "example.org",
    "platform_admin_emails": "Ops@Example.org",
}


# --- Production configuration ----------------------------------------------------------------


def test_safe_production_settings_are_accepted() -> None:
    settings = Settings(**SAFE_PROD)
    assert settings.email_allowed("Ana@Example.org") and not settings.email_allowed("eve@evil.test")
    assert not settings.email_allowed(None), "unverified or missing email never passes an allowlist"
    assert settings.effective_signup_mode == "invite", "prod defaults to invite-only sign-in"
    assert settings.effective_workspace_creation == "platform_admins"
    assert settings.is_platform_admin("ops@example.org") and not settings.is_platform_admin("ana@example.org")
    without_allowlist = Settings(**{**SAFE_PROD, "allowed_email_domains": ""})
    assert without_allowlist.effective_signup_mode == "invite", "no allowlist no longer means anyone"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"database_url": None}, "AOS_DATABASE_URL"),
        ({"cookie_secure": False}, "AOS_COOKIE_SECURE"),
        ({"oidc_issuer": "http://login.example.org"}, "AOS_OIDC_ISSUER"),
        ({"oidc_issuer": "https://localhost:8001"}, "dev OIDC issuer"),
        ({"oidc_client_id": "aos-local"}, "dev OIDC issuer"),
        ({"oidc_backchannel_url": "http://127.0.0.1:8001"}, "AOS_OIDC_BACKCHANNEL_URL"),
        ({"public_url": "http://aos.example.org"}, "AOS_PUBLIC_URL"),
        ({"platform_admin_emails": ""}, "AOS_PLATFORM_ADMIN_EMAILS"),
        ({"signup_mode": "open", "agent_mode": "llm"}, "AOS_SIGNUP_MODE"),
        ({"crash_at": "after_research"}, "AOS_CRASH_AT"),
    ],
)
def test_unsafe_production_settings_refuse_to_start(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        create_app(Settings(**{**SAFE_PROD, **override}))


def test_worker_and_migrations_need_only_the_database_in_production() -> None:
    """The worker and the pre-deploy migration serve no HTTP: no sign-in, cookie or public URL
    settings. The web app still refuses to start without them."""
    worker = Settings(env="prod", database_url="postgresql://u:p@db.internal:5432/aos")
    assert worker.sqlalchemy_url().startswith("postgresql+psycopg://")
    with pytest.raises(ValueError, match="AOS_OIDC_ISSUER") as refused:
        create_app(worker)
    for variable in ("AOS_COOKIE_SECURE", "AOS_PUBLIC_URL", "AOS_PLATFORM_ADMIN_EMAILS"):
        assert variable in str(refused.value)
    with pytest.raises(ValueError, match="AOS_DATABASE_URL"):
        Settings(env="prod", database_url=None)


def test_render_external_url_is_the_public_url_unless_one_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """F4: Render gives every web service RENDER_EXTERNAL_URL, so the blueprint needs no
    AOS_PUBLIC_URL prompt. An explicit AOS_PUBLIC_URL (a custom domain) still wins."""
    monkeypatch.delenv("AOS_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://aos-web-x1y2.onrender.com/")
    settings = Settings(**{k: v for k, v in SAFE_PROD.items() if k != "public_url"})
    assert settings.public_url == "https://aos-web-x1y2.onrender.com"
    assert settings.oidc_redirect_uri == "https://aos-web-x1y2.onrender.com/api/v1/auth/callback"
    assert settings.web_problems() == []
    monkeypatch.setenv("AOS_PUBLIC_URL", "https://research.example.org")
    assert Settings().public_url == "https://research.example.org"
    assert Settings(public_url="https://given.example.org").public_url == "https://given.example.org"


def test_unreachable_identity_provider_sends_people_back_with_a_clear_reason(
    client: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    import httpx

    from app.auth.deps import get_oidc_client
    from app.auth.oidc import OidcClient

    settings = Settings(oidc_issuer="http://127.0.0.1:9", public_url="http://testserver", env="test")
    app.dependency_overrides[get_oidc_client] = lambda: OidcClient(
        settings, httpx.Client(timeout=1, trust_env=False)
    )
    try:
        response = client.get("/api/v1/auth/login", follow_redirects=False)
    finally:
        app.dependency_overrides.pop(get_oidc_client, None)
    assert response.status_code == 302
    assert response.headers["location"] == "/signin?error=provider_unavailable"
    assert "AOS_OIDC_ISSUER" in caplog.text, "operators get the actionable detail in the log"


def test_production_app_hides_openapi_and_docs() -> None:
    prod = TestClient(create_app(Settings(**SAFE_PROD)))
    assert prod.get("/api/openapi.json").status_code == 404
    assert prod.get("/api/docs").status_code == 404
    dev = TestClient(create_app(Settings(env="test")))
    assert dev.get("/api/openapi.json").status_code == 200


# --- Sign-in allowlist -----------------------------------------------------------------------


@pytest.fixture
def allowlist(client: TestClient) -> Callable[[str], None]:
    def apply(emails: str) -> None:
        settings = get_settings().model_copy(update={"allowed_emails": emails})
        app.dependency_overrides[get_settings] = lambda: settings

    yield apply
    app.dependency_overrides.pop(get_settings, None)


def test_allowlist_refuses_uninvited_accounts_without_creating_a_user(
    client: TestClient, db: Session, oidc_against: Any, allowlist: Callable[[str], None]
) -> None:
    allowlist("bob@example.test")
    denied = sign_in_via_dev_issuer(client, "dev-alice")
    assert denied.status_code == 302 and denied.headers["location"] == "/signin?error=not_allowed"
    assert "aos_session" not in denied.headers.get("set-cookie", ""), "no session for a refused account"
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "alice@example.test")) == 0
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.denied")).one()
    assert "alice" not in str(event.details), "the refused address is not stored"

    allowed = sign_in_via_dev_issuer(client, "dev-bob")
    assert allowed.status_code == 302 and allowed.headers["location"] == "/runs"


# --- Request limits and readiness ------------------------------------------------------------


def test_oversized_json_bodies_are_rejected_before_parsing(client: TestClient) -> None:
    limit = get_settings().max_request_bytes
    declared = client.post(
        "/api/v1/runs", content=b"x" * (limit + 1), headers={"content-type": "application/json"}
    )
    assert declared.status_code == 413 and declared.json()["error"]["code"] == "payload_too_large"

    def chunks() -> Any:
        for _ in range(3):
            yield b"y" * (limit // 2 + 1)

    streamed = client.post("/api/v1/runs", content=chunks(), headers={"content-type": "application/json"})
    assert streamed.status_code == 413, "chunked bodies without Content-Length are counted too"
    assert client.post("/api/v1/runs", json={"x": 1}).status_code == 401, "normal bodies pass through"


def test_readiness_requires_the_schema_at_the_code_migration_head(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import schema_state

    assert client.get("/readyz").status_code == 200
    monkeypatch.setattr(schema_state, "migration_heads", lambda: frozenset({"9999"}))
    not_ready = client.get("/readyz")
    assert not_ready.status_code == 503 and "migration head" in not_ready.json()["error"]["message"]
    assert client.get("/healthz").status_code == 200, "liveness does not depend on the database"


# --- Single-origin SPA -----------------------------------------------------------------------


def test_api_serves_the_built_frontend_with_client_side_routing(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    spa = TestClient(create_app(Settings(env="test", static_dir=tmp_path)))

    root = spa.get("/")
    assert root.status_code == 200 and "id=root" in root.text
    assert "frame-ancestors 'none'" in root.headers["content-security-policy"]
    deep = spa.get("/runs/123")
    assert deep.status_code == 200 and "id=root" in deep.text, "browser refresh on a client route"
    asset = spa.get("/assets/app-abc123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    api_missing = spa.get("/api/v1/does-not-exist")
    assert api_missing.status_code == 404 and api_missing.json()["error"]["code"] == "not_found"
    assert spa.get("/healthz").json()["status"] == "ok", "API routes win over the SPA fallback"
    assert "nope" not in spa.get("/../secret.txt").text and "nope" not in spa.get("/%2e%2e/secret.txt").text


def test_missing_frontend_build_fails_fast_with_an_actionable_message(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"index\.html"):
        create_app(Settings(env="test", static_dir=tmp_path))


# --- Run deletion, retention, audit ----------------------------------------------------------


@pytest.fixture
def team(
    make_user: Callable[..., User], make_workspace: Callable[..., Workspace], checkpointer_ready: None
) -> dict[str, Any]:
    analyst, reviewer, admin = make_user("Ana"), make_user("Rev"), make_user("Adm")
    workspace = make_workspace("Team", {analyst: Role.ANALYST, reviewer: Role.REVIEWER, admin: Role.ADMIN})
    return {"analyst": analyst, "reviewer": reviewer, "admin": admin, "workspace": workspace}


def finished_run_with_export(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> str:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    assert work(run_id) == "waiting_plan"
    assert decide(client, analyst, run_id, "plan").status_code == 201
    assert work(run_id) == "waiting_report"
    reviewer = login(team["reviewer"])
    assert decide(client, reviewer, run_id, "report").status_code == 201
    assert work(run_id) == "done"
    exported = client.post(f"/api/v1/reports/{run_id}/versions/1/export", headers=reviewer.headers)
    assert exported.status_code == 200
    return run_id


def checkpoint_rows(db: Session, run_id: str) -> int:
    return db.scalar(text("SELECT count(*) FROM lg.checkpoints WHERE thread_id = :t"), {"t": run_id}) or 0


def test_admin_deletes_a_finished_run_completely_and_the_audit_trail_survives(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = finished_run_with_export(client, team, login)
    export = db.scalars(select(ReportExport).where(ReportExport.run_id == uuid.UUID(run_id))).one()
    object_key = export.object_key
    store = get_object_store()
    assert store.get(object_key) and checkpoint_rows(db, run_id) > 0

    analyst = login(team["analyst"])
    assert client.delete(f"/api/v1/runs/{run_id}", headers=analyst.headers).status_code == 403
    admin = login(team["admin"])
    assert client.delete(f"/api/v1/runs/{run_id}", headers=admin.headers).status_code == 204

    db.expire_all()
    assert db.get(Run, uuid.UUID(run_id)) is None
    assert checkpoint_rows(db, run_id) == 0, "workflow checkpoints are removed too"
    with pytest.raises(FileNotFoundError):
        store.get(object_key)
    assert client.get(f"/api/v1/runs/{run_id}", headers=admin.headers).status_code == 404
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.target == run_id)).all()
    assert "report.exported" in actions and "run.delete" in actions, "earlier audit records are kept"


def test_active_runs_cannot_be_deleted(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    run_id = start_run(client, analyst, team["workspace"])
    admin = login(team["admin"])
    response = client.delete(f"/api/v1/runs/{run_id}", headers=admin.headers)
    assert response.status_code == 409 and "cancel" in response.json()["error"]["message"]


def test_audit_log_is_append_only_but_survives_user_deletion(
    db: Session, make_user: Callable[..., User]
) -> None:
    user = make_user("Gone")
    db.add(AuditEvent(action="test.event", actor_user_id=user.id, target="x", details={}))
    db.commit()
    event_id = db.scalar(select(AuditEvent.id).where(AuditEvent.action == "test.event"))
    with pytest.raises(Exception, match="append-only"):
        db.execute(update(AuditEvent).where(AuditEvent.id == event_id).values(action="tampered"))
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": event_id})
    db.rollback()
    db.delete(db.get(User, user.id))
    db.commit()
    kept = db.get(AuditEvent, event_id)
    assert kept is not None and kept.actor_user_id is None and kept.action == "test.event"


def test_audit_log_is_admin_only_and_content_free(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    run_id = finished_run_with_export(client, team, login)
    url = f"/api/v1/workspaces/{team['workspace'].id}/audit"
    assert client.get(url, headers=login(team["reviewer"]).headers).status_code == 403
    events = client.get(url, headers=login(team["admin"]).headers).json()
    actions = [e["action"] for e in events]
    assert {"run.create", "plan.approve", "report.approve", "report.exported"} <= set(actions)
    assert events == sorted(events, key=lambda e: -e["id"]), "newest first"
    brief_topic = client.get(f"/api/v1/runs/{run_id}").json()["topic"]
    assert brief_topic not in str(events), "no report or brief content in the audit log"


def test_retention_sweep_removes_old_finished_runs_and_uploads_only(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    old_run = finished_run_with_export(client, team, login)
    analyst = login(team["analyst"])
    active_run = start_run(client, analyst, team["workspace"])
    upload = client.post(
        f"/api/v1/workspaces/{team['workspace'].id}/uploads",
        files={"file": ("notes.txt", b"Retention test document about backups.", "text/plain")},
        headers=analyst.headers,
    ).json()
    with get_sessionmaker()() as s:
        s.execute(update(Run).values(updated_at=func.now() - text("interval '40 days'")))
        s.execute(update(Upload).values(created_at=func.now() - text("interval '40 days'")))
        s.commit()

    done = sweep(get_sessionmaker(), run_days=30, upload_days=30)
    assert done.runs == 1 and done.uploads == 1
    db.expire_all()
    assert db.get(Run, uuid.UUID(old_run)) is None
    assert db.get(Run, uuid.UUID(active_run)) is not None, "unfinished runs are never swept"
    assert db.get(Upload, uuid.UUID(upload["id"])) is None
    actions = set(db.scalars(select(AuditEvent.action)).all())
    assert {"run.retention_delete", "upload.retention_delete"} <= actions
    assert sweep(get_sessionmaker(), run_days=0, upload_days=0).runs == 0, "0 disables the sweep"


# --- Worker resilience -----------------------------------------------------------------------


def test_seeded_demo_opens_on_a_plan_awaiting_approval_and_is_idempotent(
    db: Session, checkpointer_ready: None
) -> None:
    from app.cli import DEMO_WORKSPACE, seed_demo, seed_sample_run

    workspaces = seed_demo(db, "https://issuer.test")
    run_id = seed_sample_run(db, "https://issuer.test", workspaces[DEMO_WORKSPACE])
    db.expire_all()
    run = db.get(Run, uuid.UUID(run_id))
    assert run is not None and run.state == "AWAITING_PLAN_APPROVAL"
    assert seed_sample_run(db, "https://issuer.test", workspaces[DEMO_WORKSPACE]) == run_id
    assert seed_demo(db, "https://issuer.test")[DEMO_WORKSPACE].id == workspaces[DEMO_WORKSPACE].id


# --- Worker resilience -----------------------------------------------------------------------


def test_worker_loop_survives_a_database_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"worker_poll_seconds": 0.01})
    stopping = threading.Event()
    calls: list[str] = []

    def flaky_pass(_: Settings, **__: Any) -> str:
        calls.append("pass")
        if len(calls) <= 2:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        if len(calls) >= 4:
            stopping.set()
        return "no_job"

    monkeypatch.setattr(runner, "_maintenance", lambda *_: None)
    runner.run_loop(settings, "w-test", stopping, pass_fn=flaky_pass, max_delay=0.05)
    assert len(calls) >= 4, "the loop kept polling after the outage instead of exiting"


def test_worker_waits_for_migrations_before_starting(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    from app.db import schema_state

    stopping = threading.Event()
    checks: list[int] = []
    real_current = schema_state.current_revisions

    def lagging(session: Session) -> frozenset[str]:
        checks.append(1)
        return frozenset({"0001"}) if len(checks) < 3 else real_current(session)

    monkeypatch.setattr(schema_state, "current_revisions", lagging)
    runner.wait_for_database(get_settings(), stopping, max_delay=0.01)
    assert len(checks) == 3, "the worker waited until the API's migration reached head"
