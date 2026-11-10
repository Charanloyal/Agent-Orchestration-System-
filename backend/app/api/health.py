import hmac
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.auth.deps import AppSettings, DbSession
from app.db import schema_state
from app.errors import AppError, NotFound, Unauthenticated
from app.observability.metrics import http_metrics, workflow_metrics
from app.version import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class LivenessResponse(HealthResponse):
    version: str
    commit: str | None


class VersionResponse(BaseModel):
    version: str
    commit: str | None
    migration_head: str


class NotReady(AppError):
    status_code = 503
    code = "not_ready"


def build_commit() -> str | None:
    """The deployed commit, shortened. Render sets RENDER_GIT_COMMIT; elsewhere AOS_BUILD_COMMIT may."""
    commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("AOS_BUILD_COMMIT")
    return commit[:12] if commit else None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness (kept for the Day-1 frontend check)."""
    return HealthResponse(status="ok")


@router.get("/healthz", response_model=LivenessResponse)
def healthz() -> LivenessResponse:
    """Liveness: the process is serving requests. Checks no dependencies. Names the release and
    commit, which the UI footer shows, so a demo shows exactly what is running."""
    return LivenessResponse(status="ok", version=__version__, commit=build_commit())


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    """Which build is serving, for deploy and rollback checks (scripts/smoke_prod.py). No
    database access, no secrets."""
    return VersionResponse(
        version=__version__,
        commit=build_commit(),
        migration_head=",".join(sorted(schema_state.migration_heads())),
    )


@router.get("/readyz", response_model=HealthResponse)
def readyz(db: DbSession) -> HealthResponse:
    """Readiness: the database is reachable *and* its schema is one this code can run on: the
    code's head revision, or a newer revision that declares this code compatible (ADR 0020).
    A deploy whose migrations did not run must not receive traffic (Render health check)."""
    try:
        status = schema_state.schema_status(db)
    except Exception as exc:
        raise NotReady("Database unavailable or not migrated") from exc
    if not status.compatible:
        raise NotReady(status.reason)
    return HealthResponse(status="ok")


@router.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
def metrics(
    db: DbSession, settings: AppSettings, authorization: Annotated[str | None, Header()] = None
) -> str:
    """Prometheus scrape endpoint. Requires `Authorization: Bearer <AOS_METRICS_TOKEN>` when a
    token is configured; without one it is only served outside production. Metrics carry
    counts and durations only: no run content, user names, or IDs."""
    token = settings.metrics_token.get_secret_value() if settings.metrics_token else None
    if token is None and settings.env == "prod":
        raise NotFound("Not found")
    if token is not None and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise Unauthenticated("Metrics token required")
    return "\n".join([*http_metrics.render(), *workflow_metrics(db)]) + "\n"
