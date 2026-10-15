from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.deps import DbSession
from app.errors import AppError

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
