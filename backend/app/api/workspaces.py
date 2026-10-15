import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import Integer, cast, func, select

from app.auth.deps import CurrentPrincipal, DbSession, WorkspaceAccess, workspace_access
from app.db.models import Brief, BudgetReservation, Membership, Role, Run, User, Workspace
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


class UsageTotals(BaseModel):
    runs: int
    committed: Decimal
    reconciled: Decimal
    uncertain: Decimal
    llm_input_tokens: int
    llm_output_tokens: int
    calls: int


class UsageDay(BaseModel):
    day: date
    committed: Decimal
    calls: int


class UsageStep(BaseModel):
    step: str
    kind: str
    calls: int
    committed: Decimal
    input_tokens: int
    output_tokens: int


class UsageRun(BaseModel):
    run_id: uuid.UUID
    topic: str
    state: str
    created_at: datetime
    committed: Decimal
    budget: Decimal


class WorkspaceUsageOut(BaseModel):
    days: int
    since: datetime
    totals: UsageTotals
    by_day: list[UsageDay]
    by_step: list[UsageStep]
    top_runs: list[UsageRun]
    note: str


@router.get("/{workspace_id}/usage", response_model=WorkspaceUsageOut)
def workspace_usage(
    workspace_id: uuid.UUID,
    access: Annotated[WorkspaceAccess, Depends(workspace_access(Action.USAGE_READ))],
    db: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> WorkspaceUsageOut:
    """Estimated spend for the workspace over the last `days` days (by reservation time)."""
    since = db.scalar(select(func.now() - timedelta(days=days)))
    assert since is not None
    spend = func.coalesce(BudgetReservation.actual_cost, BudgetReservation.estimated_cost)
    tokens_in = func.coalesce(cast(BudgetReservation.usage["input_tokens"].astext, Integer), 0)
    tokens_out = func.coalesce(cast(BudgetReservation.usage["output_tokens"].astext, Integer), 0)
    scope = (BudgetReservation.workspace_id == workspace_id, BudgetReservation.created_at >= since)

    totals = db.execute(
        select(
            func.count(func.distinct(BudgetReservation.run_id)),
            func.coalesce(func.sum(spend), 0),
            func.coalesce(
                func.sum(BudgetReservation.actual_cost).filter(BudgetReservation.status == "reconciled"), 0
            ),
            func.coalesce(
                func.sum(BudgetReservation.actual_cost).filter(BudgetReservation.uncertain.is_(True)), 0
            ),
            func.coalesce(func.sum(tokens_in), 0),
            func.coalesce(func.sum(tokens_out), 0),
            func.count(),
        ).where(*scope)
    ).one()
    day = func.date_trunc("day", BudgetReservation.created_at)
    by_day = db.execute(
        select(day, func.coalesce(func.sum(spend), 0), func.count()).where(*scope).group_by(day).order_by(day)
    ).all()
    by_step = db.execute(
        select(
            BudgetReservation.step,
            BudgetReservation.kind,
            func.count(),
            func.coalesce(func.sum(spend), 0),
            func.coalesce(func.sum(tokens_in), 0),
            func.coalesce(func.sum(tokens_out), 0),
        )
        .where(*scope)
        .group_by(BudgetReservation.step, BudgetReservation.kind)
        .order_by(BudgetReservation.step, BudgetReservation.kind)
    ).all()
    run_spend = func.coalesce(func.sum(spend), 0).label("committed")
    top = db.execute(
        select(Run.id, Brief.body, Run.state, Run.created_at, run_spend)
        .join(Brief, Brief.id == Run.brief_id)
        .join(BudgetReservation, BudgetReservation.run_id == Run.id)
        .where(Run.workspace_id == workspace_id, *scope)
        .group_by(Run.id, Brief.body, Run.state, Run.created_at)
        .order_by(run_spend.desc())
        .limit(10)
    ).all()
    return WorkspaceUsageOut(
        days=days,
        since=since,
        totals=UsageTotals(
            runs=totals[0],
            committed=totals[1],
            reconciled=totals[2],
            uncertain=totals[3],
            llm_input_tokens=totals[4],
            llm_output_tokens=totals[5],
            calls=totals[6],
        ),
        by_day=[UsageDay(day=d.date(), committed=c, calls=n) for d, c, n in by_day],
        by_step=[
            UsageStep(step=s, kind=k, calls=n, committed=c, input_tokens=i, output_tokens=o)
            for s, k, n, c, i, o in by_step
        ],
        top_runs=[
            UsageRun(
                run_id=rid,
                topic=str(body.get("topic", "")),
                state=state,
                created_at=created,
                committed=committed,
                budget=Decimal(str(body.get("budget", {}).get("max_estimated_cost", "0"))),
            )
            for rid, body, state, created, committed in top
        ],
        note=(
            "Estimated from the configured price schedule and provider-reported usage; "
            "'uncertain' covers calls that may have been billed but never confirmed. "
            "Check the provider's billing console for invoiced amounts."
        ),
    )
