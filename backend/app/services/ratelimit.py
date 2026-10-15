"""Fixed-window rate limits in PostgreSQL (ADR 0016, threat model T9/T15).

Counters live in the database so every API process shares them. A rejected request still
counts: retrying faster never helps. Each check is its own short transaction, independent of
the request's transaction, so a request that later fails is still counted.
"""

import hashlib
import math
import uuid
from collections.abc import Callable

from fastapi import Request
from sqlalchemy import text

from app.auth.deps import AppSettings, CurrentPrincipal
from app.db.session import get_sessionmaker
from app.errors import TooManyRequests

_HIT = text(
    """
    INSERT INTO rate_limit_counters (key, window_start, count)
    VALUES (:key, to_timestamp(floor(extract(epoch FROM now()) / :window) * :window), 1)
    ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limit_counters.count + 1
    RETURNING count,
              extract(epoch FROM window_start + make_interval(secs => :window) - now()) AS remaining
    """
)


def enforce(key: str, limit: int, window_seconds: int) -> None:
    if limit <= 0:
        return
    with get_sessionmaker()() as session, session.begin():
        count, remaining = session.execute(_HIT, {"key": key[:120], "window": window_seconds}).one()
    if count > limit:
        retry_after = max(1, math.ceil(float(remaining)))
        raise TooManyRequests(
            f"Too many requests; try again in {retry_after} s",
            details={"limit": limit, "window_seconds": window_seconds},
            headers={"Retry-After": str(retry_after)},
        )


def _ip_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return hashlib.sha256(host.encode()).hexdigest()[:32]


def user_limit(action: str) -> Callable[..., None]:
    """Dependency: per-user hourly limit for `action` (runs after authentication + CSRF)."""

    def check(principal: CurrentPrincipal, settings: AppSettings) -> None:
        limit = {
            "run_create": settings.rate_run_create_per_user_hour,
            "upload": settings.rate_upload_per_user_hour,
            "export": settings.rate_export_per_user_hour,
        }[action]
        enforce(f"{action}:user:{principal.user_id}", limit, 3600)

    return check


def workspace_run_limit(workspace_id: uuid.UUID, settings: AppSettings) -> None:
    """Call only after the caller's membership is verified, so outsiders cannot exhaust it."""
    enforce(f"run_create:ws:{workspace_id}", settings.rate_run_create_per_workspace_hour, 3600)


def login_limit(request: Request, settings: AppSettings) -> None:
    enforce(f"login:ip:{_ip_key(request)}", settings.rate_login_per_ip_5min, 300)


def purge_old_windows(days: int = 1) -> int:
    with get_sessionmaker()() as session, session.begin():
        result = session.execute(
            text("DELETE FROM rate_limit_counters WHERE window_start < now() - make_interval(days => :d)"),
            {"d": days},
        )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
