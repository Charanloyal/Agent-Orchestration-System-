import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def audit(
    db: Session,
    action: str,
    *,
    actor_user_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None = None,
    target: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an audit record in the caller's transaction. Never include secrets or source text."""
    db.add(
        AuditEvent(
            action=action,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            target=target,
            details=details or {},
        )
    )
