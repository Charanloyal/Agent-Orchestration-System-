"""Writing Style Studio API: members only, pasted text or a workspace document, nothing stored."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.models import Role, User, Workspace
from tests.conftest import LoggedIn
from tests.test_style import BOILERPLATE


@pytest.fixture
def team(make_user: Callable[..., User], make_workspace: Callable[..., Workspace]) -> dict[str, Any]:
    analyst, reviewer, outsider = (make_user(n) for n in ("Ana", "Rev", "Out"))
    home = make_workspace("Home", {analyst: Role.ANALYST, reviewer: Role.REVIEWER})
    other = make_workspace("Other", {outsider: Role.ADMIN})
    return {"analyst": analyst, "reviewer": reviewer, "outsider": outsider, "home": home, "other": other}


def post(
    client: TestClient, session: LoggedIn, workspace: Workspace, action: str, body: dict[str, Any]
) -> Any:
    return client.post(
        f"/api/v1/workspaces/{workspace.id}/style/{action}", json=body, headers=session.headers
    )


def test_analyze_pasted_text(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    reviewer = login(team["reviewer"])
    response = post(client, reviewer, team["home"], "analyze", {"text": BOILERPLATE})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "pasted text" and body["report"]["stock_phrases"] >= 8
    assert body["report"]["sentence_list"][0]["phrases"] == ["it is important to note that"]


def test_rewrite_keeps_every_fact_and_reports_before_and_after(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    response = post(client, analyst, team["home"], "rewrite", {"text": BOILERPLATE, "persona": "journalist"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["fact_lock"]["preserved"] == body["fact_lock"]["total"] > 0
        and body["fact_lock"]["missing"] == []
    )
    assert body["after"]["stock_phrases"] < body["before"]["stock_phrases"]
    assert body["original"] == BOILERPLATE and "delve" not in body["rewritten"]


def test_a_workspace_document_can_be_the_source(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    uploaded = client.post(
        f"/api/v1/workspaces/{team['home'].id}/uploads",
        files={"file": ("brief.md", BOILERPLATE.encode())},
        headers=analyst.headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    upload_id = uploaded.json()["id"]
    response = post(client, analyst, team["home"], "rewrite", {"upload_id": upload_id, "persona": "academic"})
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "brief.md" and response.json()["fact_lock"]["missing"] == []

    outsider = login(team["outsider"])
    assert post(client, outsider, team["other"], "analyze", {"upload_id": upload_id}).status_code == 404, (
        "another workspace's document is invisible"
    )
    assert post(client, outsider, team["home"], "analyze", {"text": "x"}).status_code == 404


@pytest.mark.parametrize(
    "body",
    [{}, {"text": "a", "upload_id": "00000000-0000-0000-0000-000000000000"}, {"text": "x" * 50_001}],
)
def test_exactly_one_bounded_source(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn], body: dict[str, Any]
) -> None:
    assert post(client, login(team["analyst"]), team["home"], "analyze", body).status_code == 422


def test_blank_text_and_unknown_persona_are_refused(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    assert post(client, analyst, team["home"], "analyze", {"text": "   "}).status_code == 422
    assert (
        post(client, analyst, team["home"], "rewrite", {"text": "Hi.", "persona": "pirate"}).status_code
        == 422
    )
