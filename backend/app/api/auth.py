"""Sign-in with OpenID Connect (ADR 0007, 0021).

Every way a browser sign-in can fail ends on the sign-in page with a stable `error` code the
UI explains (never a raw JSON error page):

    provider_denied       the person cancelled or refused consent at the provider
    provider_error        the provider returned another error
    provider_unavailable  the provider could not be reached
    login_expired         unknown, expired, replayed, or started in another browser
    login_failed          the provider's response did not verify
    email_unverified      the provider did not supply a verified email
    not_allowed           verified, but not invited to this deployment
    rate_limited          too many sign-in attempts from this network
"""

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.deps import AppSettings, CurrentPrincipal, DbSession, get_oidc_client
from app.auth.oidc import IdentityClaims, OidcClient, OidcError, OidcUnavailable, new_pkce_pair
from app.auth.sessions import (
    LOGIN_COOKIE,
    clear_login_cookie,
    clear_session_cookie,
    create_session,
    now_utc,
    revoke_session,
    set_login_cookie,
    set_session_cookie,
    sha256_hex,
)
from app.config import Settings
from app.db.models import Membership, OidcLoginState, User, Workspace
from app.errors import TooManyRequests
from app.services.audit import audit
from app.services.ratelimit import login_limit

log = logging.getLogger("aos.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_LOGIN_STATE_TTL = timedelta(minutes=10)


def safe_next_path(value: str | None) -> str:
    """Only same-origin relative paths; prevents open redirects."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:500]


def _to_signin(error: str, settings: Settings) -> RedirectResponse:
    response = RedirectResponse(f"/signin?error={error}", status_code=302)
    clear_login_cookie(response, settings)
    return response


class AuthConfigOut(BaseModel):
    provider_label: str
    signup_mode: Literal["invite", "request", "open"]


@router.get("/config", response_model=AuthConfigOut)
def auth_config(settings: AppSettings) -> AuthConfigOut:
    """Public: what the sign-in page should offer. Reveals no account information."""
    restricted = bool(settings.allowed_email_set or settings.allowed_domain_set)
    mode: Literal["invite", "open"] = "invite" if restricted else "open"
    return AuthConfigOut(provider_label=settings.provider_label, signup_mode=mode)


@router.get("/login", include_in_schema=True)
def login(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    oidc: Annotated[OidcClient, Depends(get_oidc_client)],
    next: Annotated[str | None, Query(max_length=500)] = None,
) -> RedirectResponse:
    try:
        login_limit(request, settings)
    except TooManyRequests:
        return _to_signin("rate_limited", settings)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = new_pkce_pair()
    try:
        url = oidc.authorization_url(state=state, nonce=nonce, code_challenge=challenge)
    except OidcError as exc:
        # Operators need the actionable detail; the browser gets a friendly page.
        log.warning("identity provider unavailable at sign-in: %s", exc.message, extra={"code": exc.code})
        return _to_signin("provider_unavailable", settings)
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
    db.commit()
    response = RedirectResponse(url, status_code=302)
    set_login_cookie(response, state, settings)
    return response


@router.get("/callback")
def callback(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    oidc: Annotated[OidcClient, Depends(get_oidc_client)],
    code: Annotated[str | None, Query(max_length=2000)] = None,
    state: Annotated[str | None, Query(max_length=500)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    if error:
        return _to_signin("provider_denied" if error == "access_denied" else "provider_error", settings)
    if not code or not state:
        return _to_signin("login_failed", settings)
    login_state = db.scalar(
        select(OidcLoginState).where(OidcLoginState.state_sha256 == sha256_hex(state)).with_for_update()
    )
    if login_state is None or login_state.expires_at < now_utc():
        return _to_signin("login_expired", settings)
    db.delete(login_state)  # single use, even if the rest fails
    db.commit()
    bound = request.cookies.get(LOGIN_COOKIE, "")
    if not secrets.compare_digest(bound.encode(), state.encode()):
        # A valid state from a different browser: someone else's sign-in, or a stale tab.
        log.info("sign-in callback without a matching login cookie")
        return _to_signin("login_expired", settings)

    try:
        tokens = oidc.exchange_code(code=code, code_verifier=login_state.code_verifier)
        identity = oidc.verify_id_token(tokens["id_token"], nonce=login_state.nonce)
    except OidcUnavailable as exc:
        log.warning("identity provider unavailable at callback: %s", exc.message)
        return _to_signin("provider_unavailable", settings)
    except OidcError as exc:
        log.warning("sign-in response did not verify: %s", exc.message)
        return _to_signin("login_failed", settings)

    if not settings.email_allowed(identity.email):
        # Authenticated by the provider but not invited to this deployment. No user row or
        # session is created; the attempt is audited without the email itself.
        reason = "email_unverified" if identity.email is None else "not_allowed"
        audit(
            db,
            "auth.denied",
            actor_user_id=None,
            details={"reason": reason, "verified_email": identity.email is not None},
        )
        db.commit()
        return _to_signin(reason, settings)
    user = upsert_user(db, identity)
    raw, session = create_session(db, user.id, settings)
    audit(db, "auth.login", actor_user_id=user.id, details={"session_id": str(session.id)})
    db.commit()

    response = RedirectResponse(login_state.next_path, status_code=302)
    set_session_cookie(response, raw, settings)
    clear_login_cookie(response, settings)
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


class DeploymentOut(BaseModel):
    environment: str
    agent_mode: str


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str
    csrf_token: str
    memberships: list[MembershipOut]
    deployment: DeploymentOut


@router.get("/me", response_model=MeOut)
def me(principal: CurrentPrincipal, db: DbSession, settings: AppSettings) -> MeOut:
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
        deployment=DeploymentOut(environment=settings.env, agent_mode=settings.agent_mode),
    )
