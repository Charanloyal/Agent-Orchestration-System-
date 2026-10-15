"""Uploads: content sniffing, limits, explicit rejections, workspace-scoped search."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.models import Role, User, Workspace
from tests.conftest import LoggedIn
from tests.pdfs import encrypt_pdf, make_pdf


@pytest.fixture
def team(make_user: Callable[..., User], make_workspace: Callable[..., Workspace]) -> dict[str, Any]:
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


def upload(client: TestClient, session: LoggedIn, workspace: Workspace, name: str, data: bytes) -> Any:
    return client.post(
        f"/api/v1/workspaces/{workspace.id}/uploads", files={"file": (name, data)}, headers=session.headers
    )


def test_text_and_pdf_uploads_are_indexed_and_searchable(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    text = upload(
        client, analyst, team["home"], "notes.md", b"# Backups\n\nNightly exports to object storage."
    )
    assert text.status_code == 201, text.text
    assert text.json()["media_type"] == "text/plain" and text.json()["chunks"] == 1

    pdf = upload(
        client,
        analyst,
        team["home"],
        "../../etc/whitepaper.pdf",
        make_pdf(["Encryption at rest uses AES-256.", "Keys rotate every 90 days."], title="Whitepaper"),
    )
    assert pdf.status_code == 201, pdf.text
    body = pdf.json()
    assert body["filename"] == "whitepaper.pdf" and body["pages"] == 2 and body["title"] == "Whitepaper"

    duplicate = upload(
        client,
        analyst,
        team["home"],
        "again.pdf",
        make_pdf(["Encryption at rest uses AES-256.", "Keys rotate every 90 days."], title="Whitepaper"),
    )
    assert duplicate.status_code == 200 and duplicate.json()["id"] == body["id"]

    hits = client.get(
        f"/api/v1/workspaces/{team['home'].id}/uploads/search", params={"q": "key rotation"}
    ).json()
    assert hits and hits[0]["filename"] == "whitepaper.pdf" and hits[0]["locator"] == "page 2, passage 1"
    assert len(client.get(f"/api/v1/workspaces/{team['home'].id}/uploads").json()) == 2


@pytest.mark.parametrize(
    ("name", "data", "status", "fragment"),
    [
        (
            "secret.pdf",
            encrypt_pdf(make_pdf(["Confidential text that is long enough."])),
            422,
            "encrypted pdf",
        ),
        ("scan.pdf", make_pdf(["", ""]), 422, "no text layer"),
        ("tool.exe", b"MZ\x90\x00binary", 415, "Only text-based"),
        ("notes.txt", b"\xff\xfe\x00b\x00a\x00d", 415, "Only text-based"),
        ("fake.txt", b"", 422, "empty"),
    ],
    ids=["encrypted", "scanned", "executable", "binary-text", "empty"],
)
def test_unsupported_documents_are_rejected_explicitly(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    name: str,
    data: bytes,
    status: int,
    fragment: str,
) -> None:
    response = upload(client, login(team["analyst"]), team["home"], name, data)
    assert response.status_code == status
    assert fragment in response.json()["error"]["message"]


def test_size_limit(client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]) -> None:
    from app.config import get_settings

    too_big = b"a" * (get_settings().upload_max_bytes + 1)
    assert upload(client, login(team["analyst"]), team["home"], "big.txt", too_big).status_code == 413


def test_search_never_crosses_workspaces(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    upload(
        client,
        login(team["outsider"]),
        team["other"],
        "other.txt",
        b"Zebra migration secrets of the other team.",
    )
    analyst = login(team["analyst"])
    upload(client, analyst, team["home"], "home.txt", b"Our zebra notes are public.")
    hits = client.get(f"/api/v1/workspaces/{team['home'].id}/uploads/search", params={"q": "zebra"}).json()
    assert [h["filename"] for h in hits] == ["home.txt"]


def test_reviewers_cannot_upload_and_only_owner_or_admin_deletes(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    assert upload(client, login(team["reviewer"]), team["home"], "r.txt", b"reviewer text").status_code == 403
    created = upload(client, login(team["analyst"]), team["home"], "a.txt", b"analyst text").json()
    url = f"/api/v1/workspaces/{team['home'].id}/uploads/{created['id']}"
    assert client.delete(url, headers=login(team["reviewer"]).headers).status_code == 403
    assert client.delete(url, headers=login(team["admin"]).headers).status_code == 204
    assert client.get(url).status_code == 404


def test_research_questions_match_any_word_but_rank_by_coverage(
    client: TestClient, db: Any, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    from app.services.uploads import search_chunks

    analyst = login(team["analyst"])
    upload(
        client,
        analyst,
        team["home"],
        "policy.md",
        b"All data is encrypted with AES-256. Keys rotate every 90 days.",
    )
    upload(client, analyst, team["home"], "office.md", b"The office kitchen rotates cleaning duty weekly.")
    question = "How often do encryption keys rotate?"
    assert search_chunks(db, team["home"].id, question) == [], "all-words semantics misses natural questions"
    hits = search_chunks(db, team["home"].id, question, match_any=True)
    assert next(h.filename for h in hits) == "policy.md"
