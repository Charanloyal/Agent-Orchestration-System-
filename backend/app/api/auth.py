import secrets
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.deps import AppSettings, CurrentPrincipal, DbSession, get_oidc_client
from app.auth.oidc import IdentityClaims, OidcClient, OidcError, new_pkce_pair
from app.auth.sessions import (
    clear_session_cookie,
    create_session,
    now_utc,
    revoke_session,
    set_session_cookie,
    sha256_hex,
)
from app.db.models import Membership, OidcLoginState, User, Workspace
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_LOGIN_STATE_TTL = timedelta(minutes=10)


def safe_next_path(value: str | None) -> str:
    """Only same-origin relative paths; prevents open redirects."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:500]


@router.get("/login", include_in_schema=True)
def login(
    db: DbSession,
    oidc: Annotated[OidcClient, Depends(get_oidc_client)],
    next: Annotated[str | None, Query(max_length=500)] = None,
) -> RedirectResponse:
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = new_pkce_pair()
    db.execute(delete(OidcLoginState).where(OidcLoginState.expires_at < now_utc()))
    db.add(
        OidcLoginState(
            state_sha256=sha256_hex(state),
            nonce=nonce,
            code_verifier=verifier,
            next_path=safe_next_path(next),
            expires_at=now_utc() + _LOGIN_STATE_TTL,
        )
    )
    url = oidc.authorization_url(state=state, nonce=nonce, code_challenge=challenge)
    db.commit()
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
def callback(
    db: DbSession,
    settings: AppSettings,
    oidc: Annotated[OidcClient, Depends(get_oidc_client)],
    code: Annotated[str | None, Query(max_length=2000)] = None,
    state: Annotated[str | None, Query(max_length=500)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse("/signin?error=provider_denied", status_code=302)
    if not code or not state:
        raise OidcError("Missing code or state")
    login_state = db.scalar(
        select(OidcLoginState).where(OidcLoginState.state_sha256 == sha256_hex(state)).with_for_update()
    )
    if login_state is None or login_state.expires_at < now_utc():
        raise OidcError("Unknown or expired login attempt")
    db.delete(login_state)  # single use, even if the rest fails
    db.commit()

    tokens = oidc.exchange_code(code=code, code_verifier=login_state.code_verifier)
    identity = oidc.verify_id_token(tokens["id_token"], nonce=login_state.nonce)
    user = upsert_user(db, identity)
    raw, session = create_session(db, user.id, settings)
    audit(db, "auth.login", actor_user_id=user.id, details={"session_id": str(session.id)})
    db.commit()

    response = RedirectResponse(login_state.next_path, status_code=302)
    set_session_cookie(response, raw, settings)
    return response


def upsert_user(db: Session, identity: IdentityClaims) -> User:
    user = db.scalar(
        select(User).where(User.oidc_issuer == identity.issuer, User.oidc_subject == identity.subject)
    )
    if user is None:
        user = User(
            oidc_issuer=identity.issuer,
            oidc_subject=identity.subject,
            email=identity.email,
            display_name=identity.name,
        )
        db.add(user)
    else:
        user.email, user.display_name = identity.email, identity.name
    user.last_login_at = now_utc()
    db.flush()
    return user


@router.post("/logout", status_code=204)
def logout(principal: CurrentPrincipal, db: DbSession, settings: AppSettings) -> Response:
    revoke_session(db, principal.session_id)
    audit(db, "auth.logout", actor_user_id=principal.user_id)
    db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    role: str


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str
    csrf_token: str
    memberships: list[MembershipOut]


@router.get("/me", response_model=MeOut)
def me(principal: CurrentPrincipal, db: DbSession) -> MeOut:
    rows = db.execute(
        select(Membership.workspace_id, Workspace.name, Membership.role)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == principal.user_id)
        .order_by(Workspace.name)
    ).all()
    return MeOut(
        user_id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        csrf_token=principal.csrf_token,
        memberships=[MembershipOut(workspace_id=w, workspace_name=n, role=r) for w, n, r in rows],
    )
