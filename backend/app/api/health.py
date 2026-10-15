import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.deps import AppSettings, DbSession
from app.errors import AppError, NotFound, Unauthenticated
from app.observability.metrics import http_metrics, workflow_metrics

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class NotReady(AppError):
    status_code = 503
    code = "not_ready"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness (kept for the Day-1 frontend check)."""
    return HealthResponse(status="ok")


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """Liveness: the process is serving requests. Checks no dependencies."""
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse)
def readyz(db: DbSession) -> HealthResponse:
    """Readiness: the database is reachable and migrated."""
    try:
        db.execute(text("SELECT 1 FROM alembic_version"))
    except Exception as exc:
        raise NotReady("Database unavailable or not migrated") from exc
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
