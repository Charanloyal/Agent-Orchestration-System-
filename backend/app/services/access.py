"""Who may sign in, and how people get access (ADR 0021).

A verified email may sign in when any of these holds, checked in this order:
1. it is a platform admin (AOS_PLATFORM_ADMIN_EMAILS);
2. it is on the environment allowlist (AOS_ALLOWED_EMAILS / AOS_ALLOWED_EMAIL_DOMAINS);
3. it is on the in-app access list (added by a platform admin, an approved request, or an
   accepted invitation);
4. it has a pending, unexpired workspace invitation;
5. the signup mode is `open`.

Access requests never reveal whether an email is known: the public endpoint answers the same
way for new, pending, approved and denied addresses.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.sessions import now_utc
from app.config import Settings
from app.db.models import (
    AccessListEntry,
    AccessRequest,
    AuthSession,
    Membership,
    Role,
    User,
    WorkspaceInvitation,
)
from app.errors import Conflict, NotFound
from app.services.audit import audit

SignInReason = Literal["platform_admin", "allowlist", "access_list", "invitation", "open"]


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class SignInDecision:
    allowed: bool
    reason: SignInReason | None = None


def pending_invitations_filter(email: str) -> tuple[ColumnElement[bool], ...]:
    return (
        WorkspaceInvitation.email == normalize_email(email),
        WorkspaceInvitation.accepted_at.is_(None),
        WorkspaceInvitation.revoked_at.is_(None),
        WorkspaceInvitation.expires_at > func.now(),
    )


def sign_in_decision(db: Session, settings: Settings, email: str | None) -> SignInDecision:
    """Decide for a *verified* email (None means the provider did not verify one)."""
    if not email:
        return SignInDecision(False)
    email = normalize_email(email)
    if settings.is_platform_admin(email):
        return SignInDecision(True, "platform_admin")
    if settings.email_on_allowlist(email):
        return SignInDecision(True, "allowlist")
    if db.scalar(select(AccessListEntry.id).where(AccessListEntry.email == email)) is not None:
        return SignInDecision(True, "access_list")
    if db.scalar(select(WorkspaceInvitation.id).where(*pending_invitations_filter(email)).limit(1)):
        return SignInDecision(True, "invitation")
    if settings.effective_signup_mode == "open":
        return SignInDecision(True, "open")
    return SignInDecision(False)


def grant_access(
    db: Session, email: str, *, source: str, added_by: uuid.UUID | None, note: str | None = None
) -> bool:
    """Put an email on the access list; returns False when it was already there."""
    inserted = db.execute(
        insert(AccessListEntry)
        .values(id=uuid.uuid4(), email=normalize_email(email), source=source, note=note, added_by=added_by)
        .on_conflict_do_nothing(index_elements=["email"])
        .returning(AccessListEntry.id)
    ).scalar_one_or_none()
    return inserted is not None


def accept_invitations(db: Session, user: User, email: str) -> list[WorkspaceInvitation]:
    """Turn the pending invitations of a just-signed-in verified email into memberships.
    An existing membership is kept as it is: an invitation never changes a role silently."""
    invitations = list(
        db.scalars(
            select(WorkspaceInvitation)
            .where(*pending_invitations_filter(email))
            .order_by(WorkspaceInvitation.created_at)
            .with_for_update()
        )
    )
    for invitation in invitations:
        if db.get(Membership, (invitation.workspace_id, user.id)) is None:
            db.add(Membership(workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role))
        invitation.accepted_at, invitation.accepted_by = now_utc(), user.id
        audit(
            db,
            "invitation.accept",
            actor_user_id=user.id,
            workspace_id=invitation.workspace_id,
            target=str(invitation.id),
            details={"role": invitation.role},
        )
    if invitations:
        grant_access(db, email, source="invitation", added_by=None)
    db.flush()
    return invitations


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(
        select(User)
        .where(func.lower(User.email) == normalize_email(email))
        .order_by(User.last_login_at.desc().nulls_last())
        .limit(1)
    ).first()


@dataclass(frozen=True)
class InviteResult:
    status: Literal["invited", "added"]
    invitation: WorkspaceInvitation | None
    user: User | None


def invite_to_workspace(
    db: Session,
    settings: Settings,
    workspace_id: uuid.UUID,
    email: str,
    role: Role,
    *,
    invited_by: uuid.UUID,
) -> InviteResult:
    """Add someone who already has an account; otherwise create an invitation that is
    accepted the first time that verified email signs in."""
    email = normalize_email(email)
    user = find_user_by_email(db, email)
    if user is not None:
        if db.get(Membership, (workspace_id, user.id)) is not None:
            raise Conflict("That person is already a member of this workspace")
        db.add(Membership(workspace_id=workspace_id, user_id=user.id, role=role))
        grant_access(db, email, source="invitation", added_by=invited_by)
        audit(
            db,
            "member.add",
            actor_user_id=invited_by,
            workspace_id=workspace_id,
            target=str(user.id),
            details={"role": role.value},
        )
        db.flush()
        return InviteResult("added", None, user)

    pending = db.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.email == email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if pending is not None:
        if pending.expires_at > now_utc():
            raise Conflict("That email already has a pending invitation to this workspace")
        pending.revoked_at = now_utc()  # expired: replaced by the new invitation
        db.flush()
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=email,
        role=role.value,
        invited_by=invited_by,
        expires_at=now_utc() + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    db.flush()
    audit(
        db,
        "invitation.create",
        actor_user_id=invited_by,
        workspace_id=workspace_id,
        target=str(invitation.id),
        details={"role": role.value, "expires_in_days": settings.invitation_ttl_days},
    )
    return InviteResult("invited", invitation, None)


def revoke_invitation(
    db: Session, workspace_id: uuid.UUID, invitation_id: uuid.UUID, *, actor_user_id: uuid.UUID
) -> None:
    invitation = db.scalar(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.id == invitation_id, WorkspaceInvitation.workspace_id == workspace_id)
        .with_for_update()
    )
    if invitation is None or invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise NotFound("Invitation not found")
    invitation.revoked_at = now_utc()
    audit(
        db,
        "invitation.revoke",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        target=str(invitation_id),
    )


def submit_access_request(
    db: Session, settings: Settings, *, email: str, name: str, message: str | None
) -> None:
    """Record a request unless the email can already sign in or already has one pending.
    The caller answers identically in every case, so the endpoint cannot be used to learn
    whether an address is known."""
    email = normalize_email(email)
    if sign_in_decision(db, settings, email).allowed:
        return
    inserted = db.execute(
        insert(AccessRequest)
        .values(id=uuid.uuid4(), email=email, name=name.strip(), message=message, status="pending")
        .on_conflict_do_nothing(index_elements=["email"], index_where=AccessRequest.status == "pending")
        .returning(AccessRequest.id)
    ).scalar_one_or_none()
    if inserted is not None:
        audit(db, "access_request.create", actor_user_id=None, target=str(inserted))


def _pending_request(db: Session, request_id: uuid.UUID) -> AccessRequest:
    request = db.get(AccessRequest, request_id, with_for_update=True)
    if request is None:
        raise NotFound("Access request not found")
    if request.status != "pending":
        raise Conflict(f"This request was already {request.status}")
    return request


def approve_request(
    db: Session,
    settings: Settings,
    request_id: uuid.UUID,
    *,
    admin_user_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    role: Role,
) -> InviteResult | None:
    request = _pending_request(db, request_id)
    request.status, request.decided_by, request.decided_at = "approved", admin_user_id, now_utc()
    grant_access(db, request.email, source="request", added_by=admin_user_id)
    result = None
    if workspace_id is not None:
        result = invite_to_workspace(
            db, settings, workspace_id, request.email, role, invited_by=admin_user_id
        )
    audit(
        db,
        "access_request.approve",
        actor_user_id=admin_user_id,
        workspace_id=workspace_id,
        target=str(request_id),
        details={"role": role.value} if workspace_id else {},
    )
    return result


def deny_request(db: Session, request_id: uuid.UUID, *, admin_user_id: uuid.UUID) -> None:
    request = _pending_request(db, request_id)
    request.status, request.decided_by, request.decided_at = "denied", admin_user_id, now_utc()
    audit(db, "access_request.deny", actor_user_id=admin_user_id, target=str(request_id))


def remove_access(db: Session, entry_id: uuid.UUID, *, admin_user_id: uuid.UUID) -> int:
    """Take an email off the access list, revoke its pending invitations, and sign it out
    everywhere. Workspace memberships stay, so access can be restored without data loss.
    Returns the number of sessions revoked."""
    entry = db.get(AccessListEntry, entry_id, with_for_update=True)
    if entry is None:
        raise NotFound("Access list entry not found")
    email = entry.email
    db.delete(entry)
    db.execute(
        update(WorkspaceInvitation).where(*pending_invitations_filter(email)).values(revoked_at=func.now())
    )
    user_ids = select(User.id).where(func.lower(User.email) == email)
    revoked = db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    audit(
        db,
        "access.remove",
        actor_user_id=admin_user_id,
        target=str(entry_id),
        details={"sessions_revoked": int(revoked.rowcount or 0)},  # type: ignore[attr-defined]
    )
    return int(revoked.rowcount or 0)  # type: ignore[attr-defined]


def purge_decided_requests(db: Session, days: int) -> int:
    if days <= 0:
        return 0
    result = db.execute(
        delete(AccessRequest).where(
            AccessRequest.status != "pending",
            AccessRequest.decided_at < func.now() - timedelta(days=days),
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
