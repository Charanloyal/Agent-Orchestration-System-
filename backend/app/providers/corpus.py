"""Offline, versioned document corpus for reproducible evaluation (ADR 0003).

Each JSON file in the corpus directory is one document:
    {"doc_id", "url", "title", "published_on", "text", "attribution"}
Ranking is BM25 over lowercase word tokens. The corpus is static, so runs are repeatable and
cost nothing; domain policy is enforced exactly as for live search.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.providers.search import SearchHit, SearchResponse

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "does",
        "each",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "what",
        "which",
        "with",
    ]
)


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    url: str
    title: str
    published_on: str | None
    text: str
    attribution: str


class CorpusSearch:
    name = "corpus"

    def __init__(self, directory: Path, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = [
            CorpusDocument(**json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]
        self._k1, self._b = k1, b
        self._tf = [Counter(tokens(f"{d.title} {d.text}")) for d in self.documents]
        self._lengths = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.documents)
        self._idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}

    def _score(self, index: int, query_terms: list[str]) -> float:
        tf, length = self._tf[index], self._lengths[index]
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if freq:
                norm = freq + self._k1 * (1 - self._b + self._b * length / self._avg)
                score += self._idf.get(term, 0.0) * freq * (self._k1 + 1) / norm
        return score

    def search(
        self,
        query: str,
        *,
        max_results: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
    ) -> SearchResponse:
        from app.contracts import SourcePolicy
        from app.tools.policy import domain_permitted

        policy = SourcePolicy(
            allowed_source_types=["public_web"],
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )
        terms = tokens(query)
        ranked = sorted(
            (
                (self._score(i, terms), i)
                for i in range(len(self.documents))
                if domain_permitted(self.documents[i].url, policy)
            ),
            key=lambda pair: (-pair[0], self.documents[pair[1]].doc_id),
        )
        hits = [
            SearchHit(
                url=d.url,
                title=d.title,
                snippet=d.text[:200],
                published_on=d.published_on,
                content=d.text,
                kind="corpus",
            )
            for score, i in ranked[:max_results]
            if score > 0
            for d in (self.documents[i],)
        ]
        return SearchResponse(hits, credits=0.0)
