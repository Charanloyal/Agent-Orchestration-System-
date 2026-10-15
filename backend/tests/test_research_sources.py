"""Research evidence end to end: fetched pages, failed fetches, uploads, workspace isolation."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Role, User, Workspace
from app.providers.search import SearchHit, SearchResponse
from app.tools.fetcher import FetchError, FetchResult
from app.workers.runner import process_one
from tests.conftest import SAMPLE_BRIEF, LoggedIn
from tests.test_workflow import decide


class ScriptedSearch:
    """Returns hits without content so the fetcher must retrieve them."""

    name = "scripted"

    def __init__(self, urls: list[str]) -> None:
        self.urls = urls

    def search(
        self, query: str, *, max_results: int, allowed_domains: list[str], blocked_domains: list[str]
    ) -> SearchResponse:
        return SearchResponse(
            [
                SearchHit(url=u, title=f"Page {i}", snippet="", published_on="2026-02-01")
                for i, u in enumerate(self.urls)
            ],
            credits=1.0,
        )


class ScriptedFetcher:
    def __init__(self, pages: dict[str, FetchResult | FetchError]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, FetchError):
            raise page
        return page


def html(url: str, body: str) -> FetchResult:
    return FetchResult(url, 200, "text/html", "utf-8", body.encode(), ())


@pytest.fixture
def team(
    make_user: Callable[..., User], make_workspace: Callable[..., Workspace], checkpointer_ready: None
) -> dict[str, Any]:
    analyst, outsider = make_user("Ana"), make_user("Out")
    return {
        "analyst": analyst,
        "outsider": outsider,
        "home": make_workspace("Home", {analyst: Role.ANALYST}),
        "other": make_workspace("Other", {outsider: Role.ADMIN}),
    }


def run_with(
    client: TestClient, session: LoggedIn, workspace: Workspace, brief: dict[str, Any], **deps: Any
) -> str:
    created = client.post(
        "/api/v1/runs",
        json={"workspace_id": str(workspace.id), "brief": brief},
        headers={**session.headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    assert process_one(get_settings(), run_id=uuid.UUID(run_id), **deps) == "waiting_plan"
    assert decide(client, session, run_id, "plan").status_code == 201
    process_one(get_settings(), run_id=uuid.UUID(run_id), **deps)
    return str(run_id)


def test_fetched_pages_become_evidence_and_failures_are_recorded_not_cited(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    good, blocked, redirected = (
        "https://docs.vendor.test/sso",
        "https://docs.vendor.test/internal",
        "https://docs.vendor.test/moved",
    )
    fetcher = ScriptedFetcher(
        {
            good: html(good, "<title>SSO guide</title><p>SAML is supported.</p><script>evil()</script>"),
            blocked: FetchError("blocked_address"),
            redirected: html("https://elsewhere.test/page", "<p>moved</p>"),
        }
    )
    brief = {
        **SAMPLE_BRIEF,
        "research_questions": ["Is SSO supported?"],
        "source_policy": {"allowed_source_types": ["vendor_docs"], "allowed_domains": ["vendor.test"]},
    }
    session = login(team["analyst"])
    run_id = run_with(
        client,
        session,
        team["home"],
        brief,
        search=ScriptedSearch([good, blocked, redirected]),
        fetcher=fetcher,
    )

    sources = {s["url"]: s for s in client.get(f"/api/v1/runs/{run_id}/sources").json()}
    assert sources[good]["fetch_status"] == "fetched" and sources[good]["title"] == "SSO guide"
    assert (
        sources[blocked]["fetch_status"] == "failed"
        and sources[blocked]["failure_reason"] == "blocked_address"
    )
    assert sources[redirected]["failure_reason"] == "redirected_outside_source_policy"

    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert {e["source_url"] for e in evidence} == {good}
    assert all("evil()" not in e["text"] for e in evidence)
    report = client.get(f"/api/v1/runs/{run_id}").json()["report"]["body"]
    cited = {eid for s in report["sections"] for c in s["claims"] for eid in c["evidence_ids"]}
    assert cited <= {e["evidence_id"] for e in evidence}, "failed fetches are never citable"

    ranked = client.get(f"/api/v1/runs/{run_id}/evidence", params={"q": "SAML"}).json()
    assert ranked and "SAML" in ranked[0]["text"]


def test_all_fetches_failing_leads_to_needs_attention(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    url = "https://docs.vendor.test/down"
    run_id = run_with(
        client,
        login(team["analyst"]),
        team["home"],
        {**SAMPLE_BRIEF, "research_questions": ["Q?"]},
        search=ScriptedSearch([url]),
        fetcher=ScriptedFetcher({url: FetchError("timeout", transient=True)}),
    )
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "NEEDS_ATTENTION" and "No evidence" in detail["outcome_reason"]


def test_uploaded_documents_are_researched_within_the_workspace_only(
    client: TestClient, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    client.post(
        f"/api/v1/workspaces/{team['other'].id}/uploads",
        files={"file": ("rival.txt", b"Rival encryption plans: quantum keys rotate hourly.")},
        headers=login(team["outsider"]).headers,
    )
    session = login(team["analyst"])
    client.post(
        f"/api/v1/workspaces/{team['home'].id}/uploads",
        files={"file": ("ours.txt", b"Our encryption at rest uses AES-256; keys rotate yearly.")},
        headers=session.headers,
    )
    brief = {
        **SAMPLE_BRIEF,
        "research_questions": ["How are encryption keys rotated?"],
        "source_policy": {"allowed_source_types": ["uploaded_documents"]},
    }
    run_id = run_with(client, session, team["home"], brief)

    plan = client.get(f"/api/v1/runs/{run_id}").json()["plan"]["body"]
    assert all(t["tools"] == ["search_uploads"] for t in plan["tasks"]), "only tools the brief allows"
    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert evidence and all(e["source_kind"] == "upload" for e in evidence)
    assert any("AES-256" in e["text"] for e in evidence)
    assert not any("Rival" in e["text"] for e in evidence)
