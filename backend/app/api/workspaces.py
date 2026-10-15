import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from app.auth.deps import CurrentPrincipal, DbSession, WorkspaceAccess, workspace_access
from app.db.models import Membership, Role, User, Workspace
from app.errors import Conflict, NotFound, Unprocessable
from app.policy.permissions import Action
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])

Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    created_at: datetime


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str
    role: str


class MemberIn(BaseModel):
    email: Email
    role: Role


class MemberRoleIn(BaseModel):
    role: Role


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(principal: CurrentPrincipal, db: DbSession) -> list[WorkspaceOut]:
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == principal.user_id)
        .order_by(Workspace.name)
    ).all()
    return [WorkspaceOut(id=w.id, name=w.name, role=r, created_at=w.created_at) for w, r in rows]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceIn, principal: CurrentPrincipal, db: DbSession) -> WorkspaceOut:
    workspace = Workspace(name=body.name)
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=principal.user_id, role=Role.ADMIN))
    audit(
        db,
        "workspace.create",
        actor_user_id=principal.user_id,
        workspace_id=workspace.id,
    )
    db.commit()
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        role=Role.ADMIN,
        created_at=workspace.created_at,
    )


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
) -> WorkspaceOut:
    workspace = db.get(Workspace, access.workspace_id)
    assert workspace is not None
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        role=access.role,
        created_at=workspace.created_at,
    )


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.WORKSPACE_READ))],
    db: DbSession,
) -> list[MemberOut]:
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == access.workspace_id)
        .order_by(User.display_name)
    ).all()
    return [MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=r) for u, r in rows]


@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=201)
def add_member(
    body: MemberIn,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.MEMBERS_MANAGE))],
    db: DbSession,
) -> MemberOut:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        raise Unprocessable("No user with that email has signed in yet")
    if db.get(Membership, (access.workspace_id, user.id)) is not None:
        raise Conflict("User is already a member")
    db.add(Membership(workspace_id=access.workspace_id, user_id=user.id, role=body.role))
    audit(
        db,
        "member.add",
        actor_user_id=access.principal.user_id,
        workspace_id=access.workspace_id,
        target=str(user.id),
        details={"role": body.role.value},
    )
    db.commit()
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=body.role,
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
def change_member_role(
    user_id: uuid.UUID,
    body: MemberRoleIn,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.MEMBERS_MANAGE))],
    db: DbSession,
) -> MemberOut:
    membership = _member_or_404(db, access.workspace_id, user_id)
    if membership.role == Role.ADMIN and body.role != Role.ADMIN:
        _ensure_other_admin(db, access.workspace_id, user_id)
    membership.role = body.role
    audit(
        db,
        "member.role_change",
        actor_user_id=access.principal.user_id,
        workspace_id=access.workspace_id,
        target=str(user_id),
        details={"role": body.role.value},
    )
    db.commit()
    return MemberOut(
        user_id=user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        role=membership.role,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(
    user_id: uuid.UUID,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.MEMBERS_MANAGE))],
    db: DbSession,
) -> Response:
    membership = _member_or_404(db, access.workspace_id, user_id)
    if membership.role == Role.ADMIN:
        _ensure_other_admin(db, access.workspace_id, user_id)
    db.delete(membership)
    audit(
        db,
        "member.remove",
        actor_user_id=access.principal.user_id,
        workspace_id=access.workspace_id,
        target=str(user_id),
    )
    db.commit()
    return Response(status_code=204)


def _member_or_404(db: DbSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    membership = db.get(Membership, (workspace_id, user_id), with_for_update=True)
    if membership is None:
        raise NotFound("Member not found")
    return membership


def _ensure_other_admin(db: DbSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    others = db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.workspace_id == workspace_id,
            Membership.role == Role.ADMIN,
            Membership.user_id != user_id,
        )
    )
    if not others:
        raise Conflict("A workspace must keep at least one admin")
