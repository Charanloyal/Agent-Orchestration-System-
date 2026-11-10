"""Access requests (public) and deployment-wide access administration (platform admins).

Admin routes answer 404 to everyone who is not a platform admin (ADR 0021), so a signed-in
member cannot even confirm that they exist.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.api.workspaces import Email
from app.auth.deps import AppSettings, DbSession, PlatformAdmin
from app.db.models import AccessListEntry, AccessRequest, Membership, Role, User, Workspace
from app.errors import Conflict, Forbidden, NotFound
from app.services import access
from app.services.audit import audit
from app.services.ratelimit import client_key, enforce

router = APIRouter(prefix="/api/v1", tags=["access"])

REQUEST_RECEIVED = (
    "Thanks. An administrator reviews requests; if yours is approved you can sign in with this email address."
)


class AccessRequestIn(BaseModel):
    email: Email
    name: str = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, max_length=1000)


class AccessRequestReceived(BaseModel):
    status: Literal["received"]
    message: str


@router.post("/access-requests", response_model=AccessRequestReceived, status_code=202)
def request_access(
    body: AccessRequestIn, request: Request, db: DbSession, settings: AppSettings
) -> AccessRequestReceived:
    """Public. The answer is identical whether the email is new, pending, already allowed or
    denied, so it cannot be used to discover accounts. Limited per client address."""
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") != settings.public_url:
        raise Forbidden("Cross-origin request rejected")
    if settings.effective_signup_mode != "request":
        raise Forbidden("This deployment does not take access requests; ask an administrator to invite you")
    enforce(
        f"access_request:ip:{client_key(request, settings)}", settings.rate_access_request_per_ip_hour, 3600
    )
    access.submit_access_request(
        db, settings, email=body.email, name=body.name, message=(body.message or "").strip() or None
    )
    db.commit()
    return AccessRequestReceived(status="received", message=REQUEST_RECEIVED)


# --- Platform admins -------------------------------------------------------------------------


class AccessSummaryOut(BaseModel):
    pending_requests: int


class AccessRequestOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    message: str | None
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None


class ApproveIn(BaseModel):
    workspace_id: uuid.UUID | None = None
    role: Role = Role.ANALYST


class ApproveOut(BaseModel):
    status: Literal["approved"]
    workspace: Literal["invited", "added"] | None


class AccessEntryIn(BaseModel):
    email: Email
    note: str | None = Field(default=None, max_length=200)


class AccessEntryOut(BaseModel):
    id: uuid.UUID
    email: str
    source: str
    note: str | None
    created_at: datetime
    added_by: str | None


class AdminWorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    members: int


@router.get("/admin/summary", response_model=AccessSummaryOut)
def admin_summary(_: PlatformAdmin, db: DbSession) -> AccessSummaryOut:
    pending = db.scalar(
        select(func.count()).select_from(AccessRequest).where(AccessRequest.status == "pending")
    )
    return AccessSummaryOut(pending_requests=pending or 0)


@router.get("/admin/access-requests", response_model=list[AccessRequestOut])
def list_access_requests(
    _: PlatformAdmin,
    db: DbSession,
    status: Annotated[Literal["pending", "decided"], Query()] = "pending",
) -> list[AccessRequestOut]:
    decider = aliased(User)
    query = select(AccessRequest, decider.display_name).outerjoin(
        decider, decider.id == AccessRequest.decided_by
    )
    if status == "pending":
        query = query.where(AccessRequest.status == "pending").order_by(AccessRequest.created_at)
    else:
        query = query.where(AccessRequest.status != "pending").order_by(AccessRequest.decided_at.desc())
    return [
        AccessRequestOut(
            id=r.id,
            email=r.email,
            name=r.name,
            message=r.message,
            status=r.status,
            created_at=r.created_at,
            decided_at=r.decided_at,
            decided_by=name,
        )
        for r, name in db.execute(query.limit(200)).all()
    ]


@router.post("/admin/access-requests/{request_id}/approve", response_model=ApproveOut)
def approve_access_request(
    request_id: uuid.UUID, body: ApproveIn, admin: PlatformAdmin, db: DbSession, settings: AppSettings
) -> ApproveOut:
    if body.workspace_id is not None and db.get(Workspace, body.workspace_id) is None:
        raise NotFound("Workspace not found")
    result = access.approve_request(
        db, settings, request_id, admin_user_id=admin.user_id, workspace_id=body.workspace_id, role=body.role
    )
    db.commit()
    return ApproveOut(status="approved", workspace=result.status if result else None)


@router.post("/admin/access-requests/{request_id}/deny", status_code=204)
def deny_access_request(request_id: uuid.UUID, admin: PlatformAdmin, db: DbSession) -> Response:
    access.deny_request(db, request_id, admin_user_id=admin.user_id)
    db.commit()
    return Response(status_code=204)


@router.get("/admin/access-list", response_model=list[AccessEntryOut])
def list_access(_: PlatformAdmin, db: DbSession) -> list[AccessEntryOut]:
    adder = aliased(User)
    rows = db.execute(
        select(AccessListEntry, adder.display_name)
        .outerjoin(adder, adder.id == AccessListEntry.added_by)
        .order_by(AccessListEntry.email)
    ).all()
    return [
        AccessEntryOut(
            id=e.id, email=e.email, source=e.source, note=e.note, created_at=e.created_at, added_by=name
        )
        for e, name in rows
    ]


@router.post("/admin/access-list", response_model=AccessEntryOut, status_code=201)
def add_access(body: AccessEntryIn, admin: PlatformAdmin, db: DbSession) -> AccessEntryOut:
    email = access.normalize_email(body.email)
    note = (body.note or "").strip() or None
    if not access.grant_access(db, email, source="admin", added_by=admin.user_id, note=note):
        raise Conflict("That email is already on the access list")
    entry = db.scalars(select(AccessListEntry).where(AccessListEntry.email == email)).one()
    audit(db, "access.add", actor_user_id=admin.user_id, target=str(entry.id))
    db.commit()
    return AccessEntryOut(
        id=entry.id,
        email=entry.email,
        source=entry.source,
        note=entry.note,
        created_at=entry.created_at,
        added_by=admin.display_name,
    )


@router.delete("/admin/access-list/{entry_id}", status_code=204)
def remove_access(entry_id: uuid.UUID, admin: PlatformAdmin, db: DbSession) -> Response:
    access.remove_access(db, entry_id, admin_user_id=admin.user_id)
    db.commit()
    return Response(status_code=204)


@router.get("/admin/workspaces", response_model=list[AdminWorkspaceOut])
def list_all_workspaces(_: PlatformAdmin, db: DbSession) -> list[AdminWorkspaceOut]:
    """Every workspace, so a request can be approved straight into one. Names and member
    counts only; platform admins see workspace content only where they are members."""
    rows = db.execute(
        select(Workspace.id, Workspace.name, func.count(Membership.user_id))
        .outerjoin(Membership, Membership.workspace_id == Workspace.id)
        .group_by(Workspace.id, Workspace.name)
        .order_by(Workspace.name)
    ).all()
    return [AdminWorkspaceOut(id=i, name=n, members=c) for i, n, c in rows]
