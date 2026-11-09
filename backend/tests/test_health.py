import pytest
from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_healthz_is_liveness_only(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


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


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    body = client.get("/api/v1/nope").json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"]
