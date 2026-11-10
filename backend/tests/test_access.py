"""Access model (ADR 0021): signup modes, invitations, access requests, the access list and
platform-admin routes. Sign-in runs through the real dev issuer over HTTP."""

import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import (
    AccessListEntry,
    AccessRequest,
    AuditEvent,
    AuthSession,
    Membership,
    Role,
    User,
    Workspace,
    WorkspaceInvitation,
)
from app.main import app
from app.services import access
from tests.conftest import LoggedIn
from tests.test_auth_oidc import sign_in_via_dev_issuer

PLATFORM_ADMIN = "boss@example.test"


@pytest.fixture
def configure(client: TestClient) -> Iterator[Callable[..., Settings]]:
    def apply(**changes: Any) -> Settings:
        settings = get_settings().model_copy(update=changes)
        app.dependency_overrides[get_settings] = lambda: settings
        return settings

    yield apply
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def team(make_user: Callable[..., User], make_workspace: Callable[..., Workspace]) -> dict[str, Any]:
    admin, analyst, boss = make_user("Adm"), make_user("Ana"), make_user("Boss")
    boss.email = PLATFORM_ADMIN
    workspace = make_workspace("Team", {admin: Role.ADMIN, analyst: Role.ANALYST})
    return {"admin": admin, "analyst": analyst, "boss": boss, "workspace": workspace}


def me(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def ask(client: TestClient, email: str, **extra: Any) -> Any:
    return client.post(
        "/api/v1/access-requests",
        json={"email": email, "name": "Someone", **extra},
        headers={"Origin": "http://testserver"},
    )


# --- Sign-in decisions -----------------------------------------------------------------------


def test_invite_mode_refuses_strangers_and_admits_invited_people(
    client: TestClient,
    db: Session,
    oidc_against: Any,
    configure: Callable[..., Settings],
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    configure(signup_mode="invite")
    refused = sign_in_via_dev_issuer(client, "dev-dana")
    assert refused.headers["location"] == "/signin?error=not_allowed"
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "dana@example.test")) == 0

    admin = login(team["admin"])
    invited = client.post(
        f"/api/v1/workspaces/{team['workspace'].id}/invitations",
        json={"email": "Dana@Example.test", "role": "reviewer"},
        headers=admin.headers,
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["status"] == "invited"
    assert invited.json()["invitation"]["email"] == "dana@example.test"

    client.cookies.clear()
    welcomed = sign_in_via_dev_issuer(client, "dev-dana", next_path="/")
    assert welcomed.headers["location"] == "/"
    body = me(client)
    assert [(m["workspace_name"], m["role"]) for m in body["memberships"]] == [("Team", "reviewer")]
    invitation = db.scalars(select(WorkspaceInvitation)).one()
    db.refresh(invitation)
    assert invitation.accepted_at is not None
    entry = db.scalars(select(AccessListEntry).where(AccessListEntry.email == "dana@example.test")).one()
    assert entry.source == "invitation", "accepted invitations keep working for later sign-ins"
    actions = set(db.scalars(select(AuditEvent.action)))
    assert {"invitation.create", "invitation.accept", "auth.denied", "auth.login"} <= actions

    client.cookies.clear()
    again = sign_in_via_dev_issuer(client, "dev-dana", next_path="/")
    assert again.headers["location"] == "/"


def test_open_mode_admits_any_verified_email(
    client: TestClient, db: Session, oidc_against: Any, configure: Callable[..., Settings]
) -> None:
    configure(signup_mode="open")
    response = sign_in_via_dev_issuer(client, "dev-erin", next_path="/")
    assert response.headers["location"] == "/"
    body = me(client)
    assert body["memberships"] == [] and body["can_create_workspace"] is True


def test_decisions_need_a_verified_email_and_respect_every_source(db: Session) -> None:
    settings = Settings(
        env="test",
        signup_mode="invite",
        platform_admin_emails=PLATFORM_ADMIN,
        allowed_email_domains="partner.test",
    )
    assert not access.sign_in_decision(db, settings, None).allowed
    assert access.sign_in_decision(db, settings, "BOSS@example.test").reason == "platform_admin"
    assert access.sign_in_decision(db, settings, "x@partner.test").reason == "allowlist"
    assert not access.sign_in_decision(db, settings, "x@elsewhere.test").allowed
    access.grant_access(db, "X@Elsewhere.test", source="admin", added_by=None)
    db.commit()
    assert access.sign_in_decision(db, settings, "x@elsewhere.test").reason == "access_list"


def test_platform_admins_sign_in_and_alone_create_workspaces_when_restricted(
    client: TestClient,
    db: Session,
    configure: Callable[..., Settings],
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    db.commit()
    configure(platform_admin_emails=PLATFORM_ADMIN, workspace_creation="platform_admins")
    member = login(team["analyst"])
    assert me(client)["can_create_workspace"] is False
    refused = client.post("/api/v1/workspaces", json={"name": "Mine"}, headers=member.headers)
    assert refused.status_code == 403 and "platform admins" in refused.json()["error"]["message"]

    boss = login(team["boss"])
    body = me(client)
    assert body["is_platform_admin"] is True and body["can_create_workspace"] is True
    created = client.post("/api/v1/workspaces", json={"name": "  New team  "}, headers=boss.headers)
    assert created.status_code == 201 and created.json()["name"] == "New team"


# --- Workspace invitations -------------------------------------------------------------------


def test_inviting_an_existing_account_adds_it_directly(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn], make_user: Any
) -> None:
    newcomer = make_user("New")
    admin = login(team["admin"])
    url = f"/api/v1/workspaces/{team['workspace'].id}/invitations"
    added = client.post(url, json={"email": newcomer.email.upper(), "role": "analyst"}, headers=admin.headers)
    assert added.status_code == 201
    assert added.json()["status"] == "added" and added.json()["member"]["display_name"] == "New"
    assert db.get(Membership, (team["workspace"].id, newcomer.id)) is not None
    again = client.post(url, json={"email": newcomer.email, "role": "analyst"}, headers=admin.headers)
    assert again.status_code == 409


def test_invitations_can_be_listed_revoked_and_renewed_after_expiry(
    client: TestClient,
    db: Session,
    oidc_against: Any,
    configure: Callable[..., Settings],
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    configure(signup_mode="invite")
    admin = login(team["admin"])
    url = f"/api/v1/workspaces/{team['workspace'].id}/invitations"
    first = client.post(url, json={"email": "dana@example.test"}, headers=admin.headers)
    assert first.status_code == 201 and first.json()["invitation"]["role"] == "analyst"
    duplicate = client.post(url, json={"email": "dana@example.test"}, headers=admin.headers)
    assert duplicate.status_code == 409

    listed = client.get(url).json()
    assert [i["email"] for i in listed] == ["dana@example.test"] and listed[0]["invited_by"] == "Adm"

    invitation_id = first.json()["invitation"]["id"]
    assert client.delete(f"{url}/{invitation_id}", headers=admin.headers).status_code == 204
    assert client.delete(f"{url}/{invitation_id}", headers=admin.headers).status_code == 404
    assert client.get(url).json() == []
    client.cookies.clear()
    assert sign_in_via_dev_issuer(client, "dev-dana").headers["location"] == "/signin?error=not_allowed"

    admin = login(team["admin"])
    renewed = client.post(url, json={"email": "dana@example.test"}, headers=admin.headers)
    assert renewed.status_code == 201
    db.execute(update(WorkspaceInvitation).values(expires_at=func.now() - timedelta(minutes=1)))
    db.commit()
    client.cookies.clear()
    assert sign_in_via_dev_issuer(client, "dev-dana").headers["location"] == "/signin?error=not_allowed"
    admin = login(team["admin"])
    replaced = client.post(url, json={"email": "dana@example.test"}, headers=admin.headers)
    assert replaced.status_code == 201, "an expired invitation does not block a new one"


def test_only_workspace_admins_manage_invitations_and_settings(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    member = login(team["analyst"])
    workspace = team["workspace"].id
    invite = client.post(
        f"/api/v1/workspaces/{workspace}/invitations",
        json={"email": "x@example.test"},
        headers=member.headers,
    )
    assert invite.status_code == 403
    assert client.get(f"/api/v1/workspaces/{workspace}/invitations").status_code == 403
    rename = client.patch(
        f"/api/v1/workspaces/{workspace}", json={"name": "Hijacked"}, headers=member.headers
    )
    assert rename.status_code == 403


def test_admins_rename_their_workspace(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    admin = login(team["admin"])
    workspace = team["workspace"].id
    renamed = client.patch(
        f"/api/v1/workspaces/{workspace}", json={"name": " Research "}, headers=admin.headers
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Research"
    assert db.scalars(select(AuditEvent.action).where(AuditEvent.workspace_id == workspace)).all() == [
        "workspace.rename"
    ]


# --- Access requests -------------------------------------------------------------------------


def test_access_requests_answer_identically_whatever_the_email(
    client: TestClient, db: Session, configure: Callable[..., Settings], team: dict[str, Any]
) -> None:
    configure(signup_mode="request", platform_admin_emails=PLATFORM_ADMIN)
    access.grant_access(db, "known@example.test", source="admin", added_by=None)
    db.commit()
    answers = [
        ask(client, "new@example.test", message="I lead the platform team"),
        ask(client, "NEW@example.test"),  # duplicate while pending
        ask(client, "known@example.test"),  # already allowed
        ask(client, PLATFORM_ADMIN),
    ]
    assert {a.status_code for a in answers} == {202}
    assert len({a.text for a in answers}) == 1, "responses must not reveal whether an email is known"
    rows = db.scalars(select(AccessRequest)).all()
    assert [(r.email, r.status, r.message) for r in rows] == [
        ("new@example.test", "pending", "I lead the platform team")
    ]
    created = db.scalars(select(AuditEvent).where(AuditEvent.action == "access_request.create")).all()
    assert len(created) == 1 and "new@" not in str(created[0].details), "no email in the audit log"


def test_access_requests_are_only_taken_in_request_mode_and_same_origin(
    client: TestClient, db: Session, configure: Callable[..., Settings]
) -> None:
    configure(signup_mode="invite")
    assert ask(client, "new@example.test").status_code == 403
    configure(signup_mode="request")
    cross = client.post(
        "/api/v1/access-requests",
        json={"email": "new@example.test", "name": "X"},
        headers={"Origin": "https://evil.example"},
    )
    assert cross.status_code == 403
    assert ask(client, "not-an-email").status_code == 422
    assert ask(client, "new@example.test", message="x" * 1001).status_code == 422


def test_access_requests_are_rate_limited_per_client(
    client: TestClient, db: Session, configure: Callable[..., Settings]
) -> None:
    configure(signup_mode="request", rate_access_request_per_ip_hour=2)
    codes = [ask(client, f"person{i}@example.test").status_code for i in range(3)]
    assert codes == [202, 202, 429]


def test_platform_admin_approves_a_request_into_a_workspace(
    client: TestClient,
    db: Session,
    oidc_against: Any,
    configure: Callable[..., Settings],
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    configure(signup_mode="request", platform_admin_emails=PLATFORM_ADMIN)
    assert ask(client, "erin@example.test", message="Please").status_code == 202
    assert sign_in_via_dev_issuer(client, "dev-erin").headers["location"] == "/signin?error=not_allowed"

    boss = login(team["boss"])
    assert client.get("/api/v1/admin/summary").json() == {"pending_requests": 1}
    pending = client.get("/api/v1/admin/access-requests").json()
    assert [(r["email"], r["message"]) for r in pending] == [("erin@example.test", "Please")]
    workspaces = client.get("/api/v1/admin/workspaces").json()
    assert [(w["name"], w["members"]) for w in workspaces] == [("Team", 2)]

    approve = f"/api/v1/admin/access-requests/{pending[0]['id']}/approve"
    approved = client.post(
        approve, json={"workspace_id": str(team["workspace"].id), "role": "reviewer"}, headers=boss.headers
    )
    assert approved.status_code == 200 and approved.json() == {"status": "approved", "workspace": "invited"}
    assert client.post(approve, json={}, headers=boss.headers).status_code == 409
    decided = client.get("/api/v1/admin/access-requests", params={"status": "decided"}).json()
    assert decided[0]["status"] == "approved" and decided[0]["decided_by"] == "Boss"
    assert client.get("/api/v1/admin/summary").json() == {"pending_requests": 0}

    client.cookies.clear()
    welcomed = sign_in_via_dev_issuer(client, "dev-erin", next_path="/")
    assert welcomed.headers["location"] == "/"
    assert [(m["workspace_name"], m["role"]) for m in me(client)["memberships"]] == [("Team", "reviewer")]


def test_denied_requests_keep_the_person_out(
    client: TestClient,
    db: Session,
    oidc_against: Any,
    configure: Callable[..., Settings],
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    configure(signup_mode="request", platform_admin_emails=PLATFORM_ADMIN)
    ask(client, "erin@example.test")
    request_id = db.scalars(select(AccessRequest.id)).one()
    boss = login(team["boss"])
    assert (
        client.post(f"/api/v1/admin/access-requests/{request_id}/deny", headers=boss.headers).status_code
        == 204
    )
    assert (
        client.post(f"/api/v1/admin/access-requests/{request_id}/deny", headers=boss.headers).status_code
        == 409
    )
    client.cookies.clear()
    assert sign_in_via_dev_issuer(client, "dev-erin").headers["location"] == "/signin?error=not_allowed"
    assert ask(client, "erin@example.test").status_code == 202, "they may ask again later"


# --- Access list -----------------------------------------------------------------------------


def test_removing_access_signs_the_person_out_but_keeps_their_work(
    client: TestClient,
    db: Session,
    configure: Callable[..., Settings],
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
) -> None:
    configure(signup_mode="invite", platform_admin_emails=PLATFORM_ADMIN)
    analyst = team["analyst"]
    boss = login(team["boss"])
    added = client.post(
        "/api/v1/admin/access-list", json={"email": analyst.email, "note": "pilot"}, headers=boss.headers
    )
    assert added.status_code == 201 and added.json()["source"] == "admin"
    duplicate = client.post("/api/v1/admin/access-list", json={"email": analyst.email}, headers=boss.headers)
    assert duplicate.status_code == 409
    listed = client.get("/api/v1/admin/access-list").json()
    assert [(e["email"], e["note"], e["added_by"]) for e in listed] == [(analyst.email, "pilot", "Boss")]

    login(analyst)
    assert me(client)["display_name"] == "Ana"
    boss = login(team["boss"])
    entry_id = added.json()["id"]
    assert client.delete(f"/api/v1/admin/access-list/{entry_id}", headers=boss.headers).status_code == 204
    assert client.delete(f"/api/v1/admin/access-list/{entry_id}", headers=boss.headers).status_code == 404

    sessions = select(func.count()).select_from(AuthSession).where(AuthSession.user_id == analyst.id)
    assert db.scalar(sessions) == 0, "signed out everywhere"
    assert db.get(Membership, (team["workspace"].id, analyst.id)) is not None, "memberships are kept"
    removal = db.scalars(select(AuditEvent).where(AuditEvent.action == "access.remove")).one()
    assert removal.details == {"sessions_revoked": 1}


def test_admin_routes_are_invisible_to_everyone_else(
    client: TestClient, db: Session, configure: Callable[..., Settings], team: dict[str, Any], login: Any
) -> None:
    configure(platform_admin_emails=PLATFORM_ADMIN)
    workspace_admin = login(team["admin"])
    some_id = uuid.uuid4()
    for method, path in [
        ("GET", "/api/v1/admin/summary"),
        ("GET", "/api/v1/admin/access-requests"),
        ("GET", "/api/v1/admin/access-list"),
        ("GET", "/api/v1/admin/workspaces"),
        ("POST", "/api/v1/admin/access-list"),
        ("POST", f"/api/v1/admin/access-requests/{some_id}/approve"),
        ("POST", f"/api/v1/admin/access-requests/{some_id}/deny"),
        ("DELETE", f"/api/v1/admin/access-list/{some_id}"),
    ]:
        body = {"email": "x@example.test"} if path.endswith("access-list") and method == "POST" else {}
        response = client.request(method, path, json=body, headers=workspace_admin.headers)
        assert response.status_code == 404, f"{method} {path}: {response.status_code}"


# --- Retention ---------------------------------------------------------------------------------


def test_decided_requests_are_purged_after_the_retention_period(db: Session) -> None:
    db.add_all(
        [
            AccessRequest(email="old@example.test", name="Old", status="denied"),
            AccessRequest(email="new@example.test", name="New", status="approved"),
            AccessRequest(email="wait@example.test", name="Wait", status="pending"),
        ]
    )
    db.flush()
    db.execute(
        update(AccessRequest)
        .where(AccessRequest.email == "old@example.test")
        .values(decided_at=func.now() - timedelta(days=91))
    )
    db.execute(
        update(AccessRequest).where(AccessRequest.email == "new@example.test").values(decided_at=func.now())
    )
    db.commit()
    assert access.purge_decided_requests(db, 90) == 1
    db.commit()
    assert sorted(db.scalars(select(AccessRequest.email))) == ["new@example.test", "wait@example.test"]
