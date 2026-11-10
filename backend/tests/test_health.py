import pytest
from fastapi.testclient import TestClient

from app.config import Settings


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_healthz_is_liveness_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.version import __version__

    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("AOS_BUILD_COMMIT", raising=False)
    assert client.get("/healthz").json() == {"status": "ok", "version": __version__, "commit": None}


def test_healthz_names_the_running_commit_for_the_demo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    assert client.get("/healthz").json()["commit"] == "0123456789ab"


def test_the_backend_version_is_the_one_release_version() -> None:
    """app/version.py is the version source; the frontend shows it from /healthz, and its
    package.json must not drift from it."""
    import json

    from app.version import __version__
    from tests.conftest import BACKEND_DIR

    package = json.loads((BACKEND_DIR.parent / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == __version__


def test_version_names_the_build_and_its_migration_head(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import schema_state
    from app.version import __version__

    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123")
    body = client.get("/version").json()
    head = ",".join(sorted(schema_state.migration_heads()))
    assert body == {"version": __version__, "commit": "0123456789ab", "migration_head": head}


def test_readyz_checks_migrated_database(client: TestClient, db: object) -> None:
    assert client.get("/readyz").status_code == 200


def test_responses_carry_request_id_and_security_headers(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"

    bogus = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert bogus.headers["x-request-id"] != "bad id with spaces"


PROD_ONLY_HEADERS = ("strict-transport-security", "cross-origin-opener-policy", "permissions-policy")


def test_production_adds_transport_isolation_and_feature_headers() -> None:
    from app.main import create_app
    from tests.test_pilot_and_lifecycle import SAFE_PROD

    with TestClient(create_app(Settings(**SAFE_PROD))) as prod:
        headers = prod.get("/healthz").headers
    assert headers["strict-transport-security"] == "max-age=31536000"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert {"camera=()", "microphone=()", "geolocation=()"} <= set(headers["permissions-policy"].split(", "))


def test_development_over_http_sends_no_hsts(client: TestClient) -> None:
    headers = client.get("/healthz").headers
    assert not any(name in headers for name in PROD_ONLY_HEADERS), "HSTS on http://127.0.0.1 would stick"


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    body = client.get("/api/v1/nope").json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"]
