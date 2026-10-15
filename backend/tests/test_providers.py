import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.providers.corpus import CorpusSearch
from app.providers.tavily import TavilySearch
from app.workflow.errors import StepFailed, TransientError


def tavily(handler: object) -> TavilySearch:
    return TavilySearch(
        SecretStr("tvly-test-key-123456"), http=httpx.Client(transport=httpx.MockTransport(handler))
    )  # type: ignore[arg-type]


def test_tavily_request_shape_and_result_mapping() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://docs.example.com/a",
                        "title": "A",
                        "content": "snippet",
                        "published_date": "2026-03-04T00:00:00Z",
                    },
                    {"url": "https://docs.example.com/b", "title": None, "content": "b"},
                    {"title": "no url"},
                ],
                "usage": {"credits": 1},
                "request_id": "r1",
            },
        )

    response = tavily(handler).search(
        "sso support", max_results=3, allowed_domains=["example.com"], blocked_domains=["bad.example"]
    )
    assert seen["auth"] == "Bearer tvly-test-key-123456"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["include_domains"] == ["example.com"] and body["exclude_domains"] == ["bad.example"]
    assert body["include_raw_content"] is False, "pages are fetched by our own safe fetcher"
    assert [h.url for h in response.hits] == ["https://docs.example.com/a", "https://docs.example.com/b"]
    assert response.hits[0].published_on == "2026-03-04" and response.hits[0].content is None
    assert response.credits == 1.0 and response.request_id == "r1"


def test_tavily_rate_limit_is_transient_with_retry_after() -> None:
    client = tavily(
        lambda r: httpx.Response(429, headers={"Retry-After": "12"}, json={"detail": {"error": "slow"}})
    )
    with pytest.raises(TransientError) as info:
        client.search("q", max_results=1, allowed_domains=[], blocked_domains=[])
    assert info.value.retry_after == 12.0


@pytest.mark.parametrize("status", [401, 432, 433, 400])
def test_tavily_auth_and_plan_errors_are_not_retried(status: int) -> None:
    client = tavily(lambda r: httpx.Response(status, json={"detail": {"error": "no"}}))
    with pytest.raises(StepFailed):
        client.search("q", max_results=1, allowed_domains=[], blocked_domains=[])


def test_tavily_server_errors_and_network_failures_are_transient() -> None:
    with pytest.raises(TransientError):
        tavily(lambda r: httpx.Response(502)).search(
            "q", max_results=1, allowed_domains=[], blocked_domains=[]
        )

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(TransientError):
        tavily(boom).search("q", max_results=1, allowed_domains=[], blocked_domains=[])


def write_doc(directory: Path, doc_id: str, url: str, title: str, text: str) -> None:
    (directory / f"{doc_id}.json").write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "url": url,
                "title": title,
                "published_on": "2026-01-01",
                "text": text,
                "attribution": "synthetic",
            }
        ),
        encoding="utf-8",
    )


def test_corpus_bm25_ranking_and_domain_policy(tmp_path: Path) -> None:
    write_doc(
        tmp_path,
        "d1",
        "https://alpha.corpus.test/sso",
        "Alpha SSO",
        "Alpha supports SAML single sign-on and SCIM.",
    )
    write_doc(
        tmp_path, "d2", "https://beta.corpus.test/pricing", "Beta pricing", "Beta costs ten dollars per seat."
    )
    write_doc(
        tmp_path, "d3", "https://gamma.corpus.test/sso", "Gamma auth", "Gamma documents OIDC sign-on only."
    )
    corpus = CorpusSearch(tmp_path)

    hits = corpus.search(
        "which tools support SAML sign-on", max_results=5, allowed_domains=[], blocked_domains=[]
    )
    assert hits.hits[0].url == "https://alpha.corpus.test/sso"
    assert all(h.kind == "corpus" and h.content for h in hits.hits)
    assert "https://beta.corpus.test/pricing" not in [h.url for h in hits.hits], (
        "zero-score docs are excluded"
    )

    blocked = corpus.search(
        "sign-on", max_results=5, allowed_domains=[], blocked_domains=["alpha.corpus.test"]
    )
    assert [h.url for h in blocked.hits] == ["https://gamma.corpus.test/sso"]
    only = corpus.search("sign-on", max_results=5, allowed_domains=["gamma.corpus.test"], blocked_domains=[])
    assert [h.url for h in only.hits] == ["https://gamma.corpus.test/sso"]
