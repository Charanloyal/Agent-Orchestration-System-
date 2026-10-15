"""FR-01: authorization matrix generated from the live route table.

New routes are covered automatically: every /api/v1 route must require a session (unless
explicitly public), unsafe methods must require CSRF, and every route with a resource ID in
its path must return 404 to members of other workspaces.
"""

import re
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.db.models import Role, User, Workspace
from app.main import app
from app.policy.permissions import ROLE_PERMISSIONS, Action
from tests.conftest import LoggedIn

PUBLIC_ROUTES = {("GET", "/api/v1/auth/login"), ("GET", "/api/v1/auth/callback")}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def api_routes() -> list[tuple[str, str]]:
    """Enumerate routes through the public OpenAPI schema (complete for every included
    router). /api/v1 routes must therefore never use include_in_schema=False."""
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
    )


ALL_ROUTES = api_routes()
PROTECTED = [(m, p) for m, p in ALL_ROUTES if (m, p) not in PUBLIC_ROUTES]


def test_route_discovery_is_not_empty() -> None:
    assert len(ALL_ROUTES) >= 10, ALL_ROUTES
    assert set(ALL_ROUTES) >= PUBLIC_ROUTES


def fill(path: str, ids: dict[str, uuid.UUID]) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(ids.get(name, uuid.uuid4()))

    return re.sub(r"\{(\w+)\}", sub, path)


BODIES: dict[tuple[str, str], dict[str, object]] = {
    ("POST", "/api/v1/workspaces"): {"name": "X"},
    ("POST", "/api/v1/workspaces/{workspace_id}/members"): {
        "email": "nobody@example.test",
        "role": "analyst",
    },
    ("PATCH", "/api/v1/workspaces/{workspace_id}/members/{user_id}"): {"role": "analyst"},
}


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_unauthenticated_requests_get_401(client: TestClient, db: object, method: str, path: str) -> None:
    response = client.request(method, fill(path, {}), json=BODIES.get((method, path)))
    assert response.status_code == 401, response.text


@pytest.fixture
def world(make_user: Callable[..., User], make_workspace: Callable[..., Workspace]) -> dict[str, object]:
    analyst, reviewer, admin, outsider = (make_user(n) for n in ("Ana", "Rev", "Adm", "Out"))
    home = make_workspace("Home", {analyst: Role.ANALYST, reviewer: Role.REVIEWER, admin: Role.ADMIN})
    other = make_workspace("Other", {outsider: Role.ADMIN})
    return {
        "analyst": analyst,
        "reviewer": reviewer,
        "admin": admin,
        "outsider": outsider,
        "home": home,
        "other": other,
    }


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p in PROTECTED if m in UNSAFE])
def test_unsafe_methods_require_csrf_and_same_origin(
    client: TestClient,
    world: dict[str, object],
    login: Callable[[User], LoggedIn],
    method: str,
    path: str,
) -> None:
    session = login(world["admin"])  # type: ignore[arg-type]
    ids = {"workspace_id": world["home"].id, "user_id": world["analyst"].id}  # type: ignore[attr-defined]
    url, body = fill(path, ids), BODIES.get((method, path))

    assert client.request(method, url, json=body).status_code == 403
    assert client.request(method, url, json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    cross = client.request(
        method,
        url,
        json=body,
        headers={**session.headers, "Origin": "https://evil.example"},
    )
    assert cross.status_code == 403


RESOURCE_ROUTES = [(m, p) for m, p in PROTECTED if "{" in p]


@pytest.mark.parametrize(("method", "path"), RESOURCE_ROUTES)
def test_other_workspace_members_get_404(
    client: TestClient,
    world: dict[str, object],
    login: Callable[[User], LoggedIn],
    method: str,
    path: str,
) -> None:
    session = login(world["outsider"])  # type: ignore[arg-type]
    ids = {"workspace_id": world["home"].id, "user_id": world["analyst"].id}  # type: ignore[attr-defined]
    response = client.request(
        method,
        fill(path, ids),
        json=BODIES.get((method, path)),
        headers=session.headers,
    )
    assert response.status_code == 404, f"{method} {path}: {response.status_code} {response.text}"


def test_workspace_list_shows_only_own_workspaces(
    client: TestClient, world: dict[str, object], login: Callable[[User], LoggedIn]
) -> None:
    login(world["outsider"])  # type: ignore[arg-type]
    names = [w["name"] for w in client.get("/api/v1/workspaces").json()]
    assert names == ["Other"]


@pytest.mark.parametrize("role", ["analyst", "reviewer"])
def test_only_admins_manage_members(
    client: TestClient,
    world: dict[str, object],
    login: Callable[[User], LoggedIn],
    role: str,
) -> None:
    session = login(world[role])  # type: ignore[arg-type]
    home = world["home"].id  # type: ignore[attr-defined]
    response = client.post(
        f"/api/v1/workspaces/{home}/members",
        json={"email": world["outsider"].email, "role": "analyst"},  # type: ignore[attr-defined]
        headers=session.headers,
    )
    assert response.status_code == 403


def test_admin_manages_members_and_last_admin_is_protected(
    client: TestClient,
    db: object,
    world: dict[str, object],
    login: Callable[[User], LoggedIn],
) -> None:
    session = login(world["admin"])  # type: ignore[arg-type]
    home, outsider, admin = world["home"].id, world["outsider"], world["admin"]  # type: ignore[attr-defined]
    added = client.post(
        f"/api/v1/workspaces/{home}/members",
        json={"email": outsider.email.upper(), "role": "reviewer"},
        headers=session.headers,
    )  # type: ignore[attr-defined]
    assert added.status_code == 201
    assert added.json()["role"] == "reviewer"
    duplicate = client.post(
        f"/api/v1/workspaces/{home}/members",
        json={"email": outsider.email, "role": "reviewer"},
        headers=session.headers,
    )  # type: ignore[attr-defined]
    assert duplicate.status_code == 409

    demote_self = client.patch(
        f"/api/v1/workspaces/{home}/members/{admin.id}",  # type: ignore[attr-defined]
        json={"role": "analyst"},
        headers=session.headers,
    )
    assert demote_self.status_code == 409
    remove_self = client.delete(f"/api/v1/workspaces/{home}/members/{admin.id}", headers=session.headers)  # type: ignore[attr-defined]
    assert remove_self.status_code == 409

    removed = client.delete(f"/api/v1/workspaces/{home}/members/{outsider.id}", headers=session.headers)  # type: ignore[attr-defined]
    assert removed.status_code == 204


def test_creator_becomes_admin(
    client: TestClient, world: dict[str, object], login: Callable[[User], LoggedIn]
) -> None:
    session = login(world["reviewer"])  # type: ignore[arg-type]
    created = client.post("/api/v1/workspaces", json={"name": "Mine"}, headers=session.headers)
    assert created.status_code == 201
    assert created.json()["role"] == "admin"


def test_validation_errors_do_not_echo_input(
    client: TestClient, world: dict[str, object], login: Callable[[User], LoggedIn]
) -> None:
    session = login(world["admin"])  # type: ignore[arg-type]
    secret = "sk-THIS-SHOULD-NOT-ECHO-1234567890"
    response = client.post("/api/v1/workspaces", json={"name": secret * 10}, headers=session.headers)
    assert response.status_code == 422
    assert secret not in response.text


def test_role_matrix_is_least_privilege() -> None:
    assert Action.REPORT_DECIDE not in ROLE_PERMISSIONS[Role.ANALYST]
    assert Action.RUN_CREATE not in ROLE_PERMISSIONS[Role.REVIEWER]
    assert Action.PLAN_DECIDE not in ROLE_PERMISSIONS[Role.REVIEWER]
    assert Action.MEMBERS_MANAGE not in ROLE_PERMISSIONS[Role.ANALYST] | ROLE_PERMISSIONS[Role.REVIEWER]
    assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(Action)


def test_expired_session_is_rejected(
    client: TestClient,
    db: object,
    world: dict[str, object],
    login: Callable[[User], LoggedIn],
) -> None:
    from sqlalchemy import update

    from app.db.models import AuthSession

    login(world["analyst"])  # type: ignore[arg-type]
    db.execute(update(AuthSession).values(expires_at=AuthSession.created_at))  # type: ignore[attr-defined]
    db.commit()  # type: ignore[attr-defined]
    assert client.get("/api/v1/auth/me").status_code == 401
