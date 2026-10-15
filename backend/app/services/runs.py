"""Run lifecycle services: idempotent creation, access checks, and human decisions."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import CurrentPrincipal, DbSession, Principal, WorkspaceAccess, check_workspace_access
from app.config import Settings
from app.contracts import (
    ApprovalDecision,
    Plan,
    PlanPolicyViolation,
    StaleApproval,
    artifact_digest,
    check_decision_matches,
    enforce_plan_policy,
)
from app.contracts import Brief as BriefSpec
from app.contracts.run_state import RunState
from app.db.models import Approval, Brief, PlanVersion, ReportVersion, Run, RunJob
from app.errors import Conflict, NotFound, Unprocessable
from app.policy.permissions import Action
from app.policy.tools import plan_policy_for
from app.services.audit import audit
from app.services.events import append_event

DECISION_ACTIONS = {"plan": Action.PLAN_DECIDE, "report": Action.REPORT_DECIDE}


def get_run(
    db: Session, principal: Principal, run_id: uuid.UUID, action: Action
) -> tuple[Run, WorkspaceAccess]:
    """Load a run and authorize `action` in its workspace. Non-members get 404."""
    run = db.get(Run, run_id)
    if run is None:
        raise NotFound("Not found")
    return run, check_workspace_access(db, principal, run.workspace_id, action)


def run_access(action: Action, *, param: str = "run_id") -> Callable[..., WorkspaceAccess]:
    """Dependency factory: authorize a run-scoped route *before* its body is parsed, so
    untrusted input is never processed for callers who may not act on the run."""

    def by_run_id(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> WorkspaceAccess:
        return get_run(db, principal, run_id, action)[1]

    def by_report_id(report_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> WorkspaceAccess:
        return get_run(db, principal, report_id, action)[1]

    return by_run_id if param == "run_id" else by_report_id


@dataclass(frozen=True)
class CreatedRun:
    run: Run
    created: bool


def create_run(
    db: Session,
    principal: Principal,
    *,
    workspace_id: uuid.UUID,
    brief: BriefSpec,
    idempotency_key: str,
    settings: Settings,
) -> CreatedRun:
    """FR-02: the same key with the same request returns the same run; a different request
    with a reused key is a conflict."""
    check_workspace_access(db, principal, workspace_id, Action.RUN_CREATE)
    request_sha = artifact_digest({"workspace_id": str(workspace_id), "brief": brief.model_dump(mode="json")})

    def existing() -> CreatedRun | None:
        row = db.scalar(
            select(Brief).where(
                Brief.workspace_id == workspace_id,
                Brief.created_by == principal.user_id,
                Brief.idempotency_key == idempotency_key,
            )
        )
        if row is None:
            return None
        if row.request_sha256 != request_sha:
            raise Conflict("Idempotency-Key was already used for a different request")
        return CreatedRun(db.scalars(select(Run).where(Run.brief_id == row.id)).one(), created=False)

    if found := existing():
        return found
    brief_row = Brief(
        workspace_id=workspace_id,
        created_by=principal.user_id,
        body=brief.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        request_sha256=request_sha,
    )
    db.add(brief_row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()  # a concurrent request with the same key won the race
        if found := existing():
            return found
        raise
    run = Run(
        workspace_id=workspace_id,
        brief_id=brief_row.id,
        created_by=principal.user_id,
        state=RunState.QUEUED.value,
        deadline_at=datetime.now(UTC) + timedelta(minutes=brief.limits.deadline_minutes),
    )
    db.add(run)
    db.flush()
    db.add(RunJob(run_id=run.id, state="QUEUED", max_attempts=settings.job_max_attempts))
    append_event(db, run.id, workspace_id, "run_created", {"questions": len(brief.research_questions)})
    audit(db, "run.create", actor_user_id=principal.user_id, workspace_id=workspace_id, target=str(run.id))
    db.commit()
    return CreatedRun(run, created=True)


def edit_plan(
    db: Session,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    base_version: int,
    plan: Plan,
) -> PlanVersion:
    """FR-04: a human edit becomes a new immutable plan version. Any earlier approval or
    pending decision on the previous version no longer applies (its digest is stale)."""
    run, access = get_run(db, principal, run_id, Action.PLAN_DECIDE)
    job = db.execute(select(RunJob).where(RunJob.run_id == run_id).with_for_update()).scalar_one()
    if job.state != "WAITING" or job.waiting_for != "plan":
        raise Conflict("The plan can only be edited while it awaits approval")
    current = latest_artifact(db, run_id, "plan")
    if current is None or current.version != base_version:
        raise Conflict("The plan changed since you opened it; reload and edit the latest version")
    brief_row = db.get(Brief, run.brief_id)
    assert brief_row is not None
    brief = BriefSpec.model_validate(brief_row.body)
    version = current.version + 1
    edited = Plan.model_validate({**plan.model_dump(mode="json"), "plan_version": version})
    try:
        enforce_plan_policy(edited, plan_policy_for(brief))
    except PlanPolicyViolation as exc:
        raise Unprocessable(f"Plan violates policy: {exc}") from exc
    row = PlanVersion(
        run_id=run_id,
        version=version,
        digest=artifact_digest(edited),
        body=edited.model_dump(mode="json"),
        author="user",
        generation={"provider": "human", "edited_from": base_version, "edited_by": str(principal.user_id)},
    )
    db.add(row)
    append_event(
        db,
        run_id,
        run.workspace_id,
        "plan_edited",
        {"version": version, "from_version": base_version, "tasks": len(edited.tasks), "role": access.role},
    )
    audit(
        db,
        "plan.edit",
        actor_user_id=principal.user_id,
        workspace_id=run.workspace_id,
        target=str(run_id),
        details={"version": version},
    )
    db.commit()
    return row


def latest_artifact(db: Session, run_id: uuid.UUID, kind: str) -> PlanVersion | ReportVersion | None:
    if kind == "plan":
        return db.scalars(
            select(PlanVersion)
            .where(PlanVersion.run_id == run_id)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        ).first()
    return db.scalars(
        select(ReportVersion)
        .where(ReportVersion.run_id == run_id)
        .order_by(ReportVersion.version.desc())
        .limit(1)
    ).first()


def decide(
    db: Session,
    principal: Principal,
    run_id: uuid.UUID,
    *,
    kind: str,
    version: int,
    digest: str,
    decision: str,
    comment: str | None,
) -> Approval:
    """FR-04: bind the decision to the exact current version and digest, check permission at
    decision time, and durably schedule resumption, all in one transaction."""
    request = ApprovalDecision(
        artifact_kind=kind,
        artifact_version=version,
        artifact_digest=digest,
        decision=decision,
        comment=comment,
    )
    run, access = get_run(db, principal, run_id, DECISION_ACTIONS[kind])
    job = db.execute(select(RunJob).where(RunJob.run_id == run_id).with_for_update()).scalar_one()
    if job.state != "WAITING" or job.waiting_for != kind:
        raise Conflict(f"Run is not awaiting a {kind} decision")
    current = latest_artifact(db, run_id, kind)
    if current is None:
        raise Conflict(f"Run has no {kind} to decide on")
    try:
        # Recomputes the digest from the stored body rather than trusting a stored digest.
        check_decision_matches(request, current.version, current.body)
    except StaleApproval as exc:
        raise Conflict(f"Stale decision: {exc}") from exc
    approval = Approval(
        run_id=run_id,
        workspace_id=run.workspace_id,
        artifact_kind=kind,
        artifact_version=version,
        artifact_digest=digest,
        decision=decision,
        comment=comment,
        decided_by=principal.user_id,
    )
    db.add(approval)
    db.flush()
    job.state, job.waiting_for, job.wait_deadline_at = "QUEUED", None, None
    job.resume_payload = {"approval_id": str(approval.id)}
    job.available_at = datetime.now(UTC)
    job.attempts = 0
    append_event(
        db,
        run_id,
        run.workspace_id,
        "decision_recorded",
        {"kind": kind, "version": version, "decision": decision, "role": access.role},
    )
    audit(
        db,
        f"{kind}.{decision}",
        actor_user_id=principal.user_id,
        workspace_id=run.workspace_id,
        target=str(run_id),
        details={"version": version},
    )
    db.commit()
    return approval
