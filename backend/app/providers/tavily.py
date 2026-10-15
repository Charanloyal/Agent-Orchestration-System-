"""Tavily search adapter (ADR 0003). https://docs.tavily.com/documentation/api-reference/endpoint/search

Pages are fetched by our own SSRF-safe fetcher rather than trusting provider-extracted text,
so provenance (retrieval time, content hash) is ours. Errors are classified: rate limits and
5xx are transient (retried by the worker with backoff); auth and plan-limit errors are not.
"""

from typing import Any

import httpx
from pydantic import SecretStr

from app.providers.search import SearchHit, SearchResponse
from app.workflow.errors import StepFailed, TransientError

TAVILY_URL = "https://api.tavily.com/search"


class TavilySearch:
    name = "tavily"

    def __init__(
        self, api_key: SecretStr, *, http: httpx.Client | None = None, timeout: float = 20.0
    ) -> None:
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=timeout)

    def search(
        self,
        query: str,
        *,
        max_results: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
    ) -> SearchResponse:
        body: dict[str, Any] = {
            "query": query[:400],
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 20)),
            "include_published_date": True,
            "include_usage": True,
            "include_answer": False,
            "include_raw_content": False,
        }
        if allowed_domains:
            body["include_domains"] = allowed_domains
        if blocked_domains:
            body["exclude_domains"] = blocked_domains
        try:
            response = self._http.post(
                TAVILY_URL, json=body, headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
            )
        except httpx.TimeoutException as exc:
            raise TransientError("search provider timeout") from exc
        except httpx.TransportError as exc:
            raise TransientError("search provider unreachable") from exc

        status = response.status_code
        if status == 429 or status >= 500:
            retry_after = response.headers.get("retry-after", "")
            raise TransientError(
                f"search provider HTTP {status}",
                retry_after=float(retry_after) if retry_after.isdigit() else None,
            )
        if status != 200:
            # 400/401/422 (bad request or key) and 432/433 (plan or pay-as-you-go limit).
            raise StepFailed("research", f"search provider rejected the request (HTTP {status})")
        data = response.json()
        hits = [
            SearchHit(
                url=str(item["url"]),
                title=str(item.get("title") or item["url"])[:500],
                snippet=str(item.get("content") or "")[:1000],
                published_on=str(item["published_date"])[:10] if item.get("published_date") else None,
            )
            for item in data.get("results", [])
            if isinstance(item, dict) and item.get("url")
        ]
        credits = float((data.get("usage") or {}).get("credits", 1))
        return SearchResponse(hits, credits=credits, request_id=data.get("request_id"))
