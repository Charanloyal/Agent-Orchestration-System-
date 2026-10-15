"""Server-side sessions. The browser holds an opaque random token in an HttpOnly cookie;
the database stores only its SHA-256. Each session also carries a CSRF token that unsafe
requests must echo in the X-CSRF-Token header."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.config import Settings
from app.db.models import AuthSession

_TOUCH_INTERVAL = timedelta(minutes=5)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now_utc() -> datetime:
    return datetime.now(UTC)


def create_session(db: Session, user_id: uuid.UUID, settings: Settings) -> tuple[str, AuthSession]:
    raw = secrets.token_urlsafe(32)
    record = AuthSession(
        token_sha256=sha256_hex(raw),
        user_id=user_id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=now_utc() + timedelta(minutes=settings.session_ttl_minutes),
    )
    db.add(record)
    db.flush()
    return raw, record


def resolve_session(db: Session, raw_token: str) -> AuthSession | None:
    record = db.scalar(select(AuthSession).where(AuthSession.token_sha256 == sha256_hex(raw_token)))
    if record is None:
        return None
    now = now_utc()
    if record.expires_at <= now:
        db.delete(record)
        db.commit()
        return None
    if now - record.last_seen_at > _TOUCH_INTERVAL:
        record.last_seen_at = now
        db.commit()
    return record


def revoke_session(db: Session, session_id: uuid.UUID) -> None:
    db.execute(delete(AuthSession).where(AuthSession.id == session_id))


def set_session_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        raw_token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
