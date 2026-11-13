"""Keyless web search from open sources with official APIs (ADR 0031): Wikipedia and arXiv.

Used when no search key is configured, so live runs cite real, public documents instead of
the deterministic test provider. Both services publish free APIs for programmatic use and ask
for a descriptive User-Agent. The text returned is the source's own (Wikipedia article text,
arXiv abstracts), never model-written; the hosts are fixed, so no user-controlled URL is
fetched here.

ADR 0033: results must share the question's distinctive words (not just generic ones such as
"pattern" or "building"), adult pages are dropped, and a small directory of official
documentation pages is offered first for well-known engineering topics. Those pages are
fetched live through the safe fetcher like any other result, so their text is the vendor's own.
"""

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.parse import quote, urlsplit

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


# Words common to questions on any subject. A result matching only these is not relevant:
# "circuit breaker pattern for building ..." must not return "Sick building syndrome".
_WEAK = frozenset(
    {"approach", "approaches", "architecture", "based", "best", "between", "build", "building"}
    | {"case", "cases", "choose", "common", "cost", "data", "design", "designs", "different"}
    | {"effect", "effects", "error", "errors", "example", "examples", "factor", "factors"}
    | {"handle", "handling", "impact", "implement", "implementation", "improve", "key", "main"}
    | {"management", "method", "methods", "model", "models", "pattern", "patterns", "performance"}
    | {"practice", "practices", "problem", "problems", "process", "rate", "real", "result"}
    | {"results", "role", "service", "services", "strategies", "strategy", "structure", "system"}
    | {"systems", "time", "tradeoff", "tradeoffs", "trade-offs", "transient", "type", "types"}
    | {"use", "used", "uses", "using", "work", "works"}
)
# Adult content never belongs in a research report unless the brief is explicitly about it.
_NSFW = re.compile(
    r"\b(?:porn\w*|sex|sexual\w*|erotic\w*|nude\w*|nudity|xxx|hentai|fetish\w*|prostitut\w*|onlyfans)\b",
    re.IGNORECASE,
)
RELEVANCE_WINDOW = 1500


def keywords(query: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.#-]*", query)
    return [w for w in words if w.lower() not in _STOP][:limit]


def strong_keywords(query: str, limit: int = 6) -> list[str]:
    return [w for w in keywords(query, 12) if w.lower() not in _WEAK][:limit]


def is_relevant(query: str, title: str, text: str) -> bool:
    """A result is kept when its title or opening text contains at least two of the question's
    keywords, one of them distinctive (or the only keyword, for a one-word question), and it is
    not adult content (unless the question itself is about that)."""
    head = f"{title}\n{text[:RELEVANCE_WINDOW]}"
    if _NSFW.search(f"{title}\n{text[:300]}") and not _NSFW.search(query):
        return False
    words = {w.lower() for w in keywords(query, 12)}
    if not words:
        return True
    lowered = head.lower()
    found = {w for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w), lowered)}
    strong = {w for w in words if w not in _WEAK}
    if strong and not found & strong:
        return False
    return len(found) >= min(2, len(words))


# Official documentation for common engineering topics: (trigger phrases, URL, title). Only the
# address is stored here; the page is fetched when cited, and the workspace domain policy applies.
CURATED_DOCS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("circuit breaker", "circuit-breaker"),
        "https://martinfowler.com/bliki/CircuitBreaker.html",
        "CircuitBreaker (Martin Fowler)",
    ),
    (
        ("raft", "leader election", "log replication", "consensus algorithm", "distributed consensus"),
        "https://raft.github.io/",
        "The Raft Consensus Algorithm",
    ),
    (
        ("server-sent events", "server sent events", "sse", "streamingresponse", "streaming response"),
        "https://fastapi.tiangolo.com/advanced/custom-response/",
        "Custom Response - HTML, Stream, File, others (FastAPI)",
    ),
    (
        ("server-sent events", "server sent events", "sse", "eventsource"),
        "https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events",
        "Using server-sent events (MDN)",
    ),
    (("qdrant", "hnsw"), "https://qdrant.tech/documentation/manage-data/indexing/", "Indexing (Qdrant)"),
    (
        ("faiss", "vector search", "similarity search", "nearest neighbor", "nearest neighbour"),
        "https://github.com/facebookresearch/faiss/wiki",
        "Faiss wiki (Meta AI Research)",
    ),
    (
        ("spark streaming", "structured streaming", "pyspark"),
        "https://spark.apache.org/docs/latest/streaming/index.html",
        "Structured Streaming Programming Guide (Apache Spark)",
    ),
    (
        ("redis", "lua script"),
        "https://redis.io/docs/latest/develop/programmability/eval-intro/",
        "Scripting with Lua (Redis)",
    ),
    (
        ("langgraph",),
        "https://docs.langchain.com/oss/python/langgraph/overview",
        "LangGraph overview (LangChain)",
    ),
    (("kubernetes", "k8s"), "https://kubernetes.io/docs/concepts/overview/", "Overview (Kubernetes)"),
    (
        ("postgresql", "postgres", "mvcc"),
        "https://www.postgresql.org/docs/current/mvcc-intro.html",
        "Concurrency Control: Introduction (PostgreSQL)",
    ),
    (("docker",), "https://docs.docker.com/get-started/docker-overview/", "What is Docker? (Docker Docs)"),
)
MAX_CURATED_PER_QUERY = 2


def curated_hits(query: str, limit: int = MAX_CURATED_PER_QUERY) -> list[SearchHit]:
    lowered = query.lower()
    hits: list[SearchHit] = []
    for triggers, url, title in CURATED_DOCS:
        if len(hits) >= limit:
            break
        if any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", lowered) for t in triggers):
            hits.append(SearchHit(url=url, title=title, snippet=title))
    return hits


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
        curated = [
            hit
            for hit in curated_hits(query)
            if _domain_allowed(_host(hit.url), allowed_domains, blocked_domains)
        ][:max_results]
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
        results = [
            [hit for hit in found if is_relevant(query, hit.title, hit.content or hit.snippet)]
            for found in results
        ]
        hits: list[SearchHit] = list(curated)
        for rank in range(max_results):  # interleave so both sources are represented
            for found in results:
                if rank < len(found) and len(hits) < max_results:
                    hits.append(found[rank])
        return SearchResponse(hits, credits=0.0)

    def _wikipedia(self, query: str, limit: int) -> list[SearchHit]:
        terms = " ".join(strong_keywords(query) or keywords(query)) or query
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
        words = strong_keywords(query, 5) or keywords(query, 5)
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


def _host(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower()


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
