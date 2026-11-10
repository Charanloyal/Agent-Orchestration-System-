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

    # Render's disk is ephemeral: if the stored original vanished, the same upload restores it.
    from app.storage import get_object_store

    store, upload_id = get_object_store(), body["id"]
    key = f"uploads/{team['home'].id}/{body['sha256']}"
    store.delete(key)
    assert not store.exists(key)
    restored = upload(
        client,
        analyst,
        team["home"],
        "again.pdf",
        make_pdf(["Encryption at rest uses AES-256.", "Keys rotate every 90 days."], title="Whitepaper"),
    )
    assert restored.status_code == 200 and restored.json()["id"] == upload_id
    assert store.exists(key)

    hits = client.get(
        f"/api/v1/workspaces/{team['home'].id}/uploads/search", params={"q": "key rotation"}
    ).json()
    assert hits and hits[0]["filename"] == "whitepaper.pdf" and hits[0]["locator"] == "page 2, passage 1"
    assert len(client.get(f"/api/v1/workspaces/{team['home'].id}/uploads").json()) == 2


def test_without_stored_files_uploads_are_indexed_searched_and_deleted(
    client: TestClient,
    team: dict[str, Any],
    login: Callable[[User], LoggedIn],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AOS_STORE_FILES=false (Render, ADR 0026): nothing reads an original back, so none is
    kept; the extracted text in Postgres is the document."""
    from app.api import uploads as uploads_api
    from app.config import get_settings
    from app.storage import DiscardingObjectStore, LocalObjectStore

    monkeypatch.setattr(uploads_api, "get_object_store", DiscardingObjectStore)
    analyst = login(team["analyst"])
    data = b"# Retention\n\nRuns are kept until an admin deletes them."
    created = upload(client, analyst, team["home"], "policy.md", data)
    assert created.status_code == 201, created.text
    key = f"uploads/{team['home'].id}/{created.json()['sha256']}"
    assert not LocalObjectStore(get_settings().object_store_dir).exists(key), "no copy on disk"
    again = upload(client, analyst, team["home"], "policy.md", data)
    assert again.status_code == 200 and again.json()["id"] == created.json()["id"]
    hits = client.get(
        f"/api/v1/workspaces/{team['home'].id}/uploads/search", params={"q": "admin deletes"}
    ).json()
    assert hits and hits[0]["filename"] == "policy.md"
    deleted = client.delete(
        f"/api/v1/workspaces/{team['home'].id}/uploads/{created.json()['id']}", headers=analyst.headers
    )
    assert deleted.status_code == 204


def test_the_store_follows_the_setting(tmp_path: Any) -> None:
    from app.config import Settings
    from app.storage import DiscardingObjectStore, LocalObjectStore, build_object_store

    assert isinstance(build_object_store(Settings(store_files=False)), DiscardingObjectStore)
    kept = build_object_store(Settings(store_files=True, object_store_dir=tmp_path))
    assert isinstance(kept, LocalObjectStore) and kept.keeps_files
    discarding = DiscardingObjectStore()
    discarding.put("uploads/x", b"data")
    discarding.delete("uploads/x")
    assert not discarding.exists("uploads/x") and not discarding.keeps_files
    with pytest.raises(FileNotFoundError):
        discarding.get("uploads/x")


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
