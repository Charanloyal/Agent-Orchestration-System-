"""Request-scoped authentication and authorization dependencies.

Every /api/v1 route except the public auth endpoints depends on `get_principal`, which also
enforces CSRF and Origin checks for unsafe methods, so a route cannot forget them.
Workspace-scoped access returns 404 (not 403) to non-members so resource IDs do not leak.
"""

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.oidc import OidcClient
from app.auth.sessions import resolve_session
from app.config import Settings, get_settings
from app.db.models import Membership, User
from app.db.session import get_db
from app.errors import Forbidden, NotFound, Unauthenticated
from app.policy.permissions import Action, is_allowed

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "x-csrf-token"

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    csrf_token: str
    email: str | None
    display_name: str


@lru_cache
def _default_oidc_client() -> OidcClient:
    return OidcClient(get_settings())


def get_oidc_client() -> OidcClient:
    return _default_oidc_client()


def get_principal(request: Request, db: DbSession, settings: AppSettings) -> Principal:
    raw = request.cookies.get(settings.session_cookie_name)
    session = resolve_session(db, raw) if raw else None
    if session is None:
        raise Unauthenticated("Sign in required")
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") != settings.public_url:
            raise Forbidden("Cross-origin request rejected")
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
            raise Forbidden("Missing or invalid CSRF token")
    user = db.get(User, session.user_id)
    if user is None:
        raise Unauthenticated("Sign in required")
    return Principal(user.id, session.id, session.csrf_token, user.email, user.display_name)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


@dataclass(frozen=True)
class WorkspaceAccess:
    workspace_id: uuid.UUID
    principal: Principal
    role: str


def check_workspace_access(
    db: Session, principal: Principal, workspace_id: uuid.UUID, action: Action
) -> WorkspaceAccess:
    membership = db.get(Membership, (workspace_id, principal.user_id))
    if membership is None:
        raise NotFound("Not found")
    if not is_allowed(membership.role, action):
        raise Forbidden(f"Your role does not permit {action.value}")
    return WorkspaceAccess(workspace_id, principal, membership.role)


def workspace_access(action: Action) -> Callable[..., WorkspaceAccess]:
    """Dependency factory for routes with a `workspace_id` path parameter."""

    def dependency(workspace_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> WorkspaceAccess:
        return check_workspace_access(db, principal, workspace_id, action)

    dependency.__name__ = f"workspace_access_{action.value.replace('.', '_')}"
    return dependency
