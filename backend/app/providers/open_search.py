"""Keyless web search from open sources with official APIs (ADR 0031): Wikipedia and arXiv.

Used when no search key is configured, so live runs cite real, public documents instead of
the deterministic test provider. Both services publish free APIs for programmatic use and ask
for a descriptive User-Agent. The text returned is the source's own (Wikipedia article text,
arXiv abstracts), never model-written; the hosts are fixed, so no user-controlled URL is
fetched here.
"""

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.parse import quote

import httpx

from app.providers.search import SearchHit, SearchResponse

log = logging.getLogger("aos.search")

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = (
    "AgentOrchestrationSystem/1.0 (academic research assistant; "
    "https://github.com/Charanloyal/Agent-Orchestration-System-)"
)
MAX_ARTICLE_CHARS = 20_000
_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_STOP = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "can", "compare", "do", "does", "for", "from"}
    | {"how", "in", "into", "is", "it", "its", "of", "on", "or", "should", "the", "their", "them"}
    | {"these", "this", "to", "vs", "what", "when", "which", "who", "why", "will", "with"}
)


def keywords(query: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.#-]*", query)
    return [w for w in words if w.lower() not in _STOP][:limit]


def _domain_allowed(domain: str, allowed: list[str], blocked: list[str]) -> bool:
    def matches(rule: str) -> bool:
        rule = rule.lower().lstrip(".")
        return domain == rule or domain.endswith("." + rule)

    if any(matches(b) for b in blocked):
        return False
    return not allowed or any(matches(a) for a in allowed)


class OpenWebSearch:
    name = "open-web"

    def __init__(self, *, client: httpx.Client | None = None, timeout_seconds: float = 6.0) -> None:
        self._client = client or httpx.Client(
            timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )

    def search(
        self,
        query: str,
        *,
        max_results: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
    ) -> SearchResponse:
        sources: list[tuple[str, Callable[[str, int], list[SearchHit]]]] = [
            ("en.wikipedia.org", self._wikipedia),
            ("arxiv.org", self._arxiv),
        ]
        results: list[list[SearchHit]] = []
        for domain, fetch in sources:
            if not _domain_allowed(domain, allowed_domains, blocked_domains):
                continue
            try:
                results.append(fetch(query, max_results))
            except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
                # A source that is down, slow or rate-limited is skipped, never retried: the task
                # records what it could not find instead of failing the run (ADR 0031).
                log.warning(
                    "open search source skipped", extra={"source": domain, "error": type(exc).__name__}
                )
        hits: list[SearchHit] = []
        for rank in range(max_results):  # interleave so both sources are represented
            for found in results:
                if rank < len(found) and len(hits) < max_results:
                    hits.append(found[rank])
        return SearchResponse(hits, credits=0.0)

    def _wikipedia(self, query: str, limit: int) -> list[SearchHit]:
        terms = " ".join(keywords(query)) or query
        found = self._client.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": terms,
                "srlimit": min(limit, 3),
                "format": "json",
            },
        )
        found.raise_for_status()
        hits = []
        for item in found.json().get("query", {}).get("search", []):
            title = str(item["title"])
            page = self._client.get(
                WIKIPEDIA_API,
                params={
                    "action": "query",
                    "prop": "extracts|revisions",
                    "rvprop": "timestamp",
                    "explaintext": 1,
                    "redirects": 1,
                    "titles": title,
                    "format": "json",
                },
            )
            page.raise_for_status()
            for data in page.json().get("query", {}).get("pages", {}).values():
                text = _clean_wikipedia(str(data.get("extract") or ""))
                if len(text) < 200:
                    continue
                revised = (data.get("revisions") or [{}])[0].get("timestamp", "")[:10] or None
                hits.append(
                    SearchHit(
                        url=f"https://en.wikipedia.org/wiki/{quote(str(data['title']).replace(' ', '_'))}",
                        title=f"{data['title']} (Wikipedia)",
                        snippet=text[:200],
                        published_on=revised,
                        content=text[:MAX_ARTICLE_CHARS],
                    )
                )
        return hits

    def _arxiv(self, query: str, limit: int) -> list[SearchHit]:
        words = keywords(query, 5)
        if not words:
            return []
        search = " AND ".join(f"all:{w}" for w in words[:3])
        _arxiv_turn()
        response = self._client.get(
            ARXIV_API, params={"search_query": search, "max_results": min(limit, 3), "sortBy": "relevance"}
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)  # noqa: S314  (fixed, trusted host; no DTDs processed)
        hits = []
        for entry in root.findall("a:entry", _ATOM):
            title = " ".join((entry.findtext("a:title", "", _ATOM) or "").split())
            summary = " ".join((entry.findtext("a:summary", "", _ATOM) or "").split())
            url = (entry.findtext("a:id", "", _ATOM) or "").replace("http://", "https://")
            if not (title and summary and url):
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=f"{title} (arXiv)",
                    snippet=summary[:200],
                    published_on=(entry.findtext("a:published", "", _ATOM) or "")[:10] or None,
                    content=f"{title}\n\n{summary}",
                )
            )
        return hits


_ARXIV_LOCK = threading.Lock()
_ARXIV_LAST = [0.0]
ARXIV_INTERVAL_SECONDS = 3.0  # arXiv API terms: no more than one request every three seconds


def _arxiv_turn() -> None:
    """Space arXiv requests across parallel research tasks."""
    with _ARXIV_LOCK:
        wait = _ARXIV_LAST[0] + ARXIV_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _ARXIV_LAST[0] = time.monotonic()


def _clean_wikipedia(text: str) -> str:
    """Plain-text extracts mark headings as '== Heading =='; keep them as their own lines and
    drop trailing reference-only sections."""
    text = re.split(r"\n==+ (?:See also|References|Notes|Further reading|External links) ==+\n", text)[0]
    text = re.sub(r"\n(=+) *(.+?) *\1\n", lambda m: f"\n\n{m.group(2)}\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
