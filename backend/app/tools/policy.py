"""Source policy enforced in code, outside any model prompt (non-negotiable #2)."""

import hashlib
from urllib.parse import urlsplit, urlunsplit

from app.contracts import SourcePolicy


def hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def domain_permitted(url: str, policy: SourcePolicy) -> bool:
    host = hostname(url)
    if not host or any(_matches(host, d) for d in policy.blocked_domains):
        return False
    return not policy.allowed_domains or any(_matches(host, d) for d in policy.allowed_domains)


def is_stale(published_on: str | None, policy: SourcePolicy) -> bool:
    return bool(policy.date_cutoff and published_on and published_on < policy.date_cutoff.isoformat())


def normalize_url(url: str) -> str:
    """Stable identity for deduplication: lowercase scheme/host, no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), (parts.hostname or "").lower(), path, parts.query, ""))


def source_id_for(url: str) -> str:
    return "src-" + hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]
