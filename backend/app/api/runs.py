"""Runs API: create (idempotent), list, inspect, timeline, live events (SSE), decisions."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select, text

from app.auth.deps import AppSettings, CurrentPrincipal, DbSession, Principal, check_workspace_access
from app.billing.meter import spend_for
from app.contracts import Brief as BriefSpec
from app.contracts import Plan as PlanSpec
from app.contracts.common import Sha256Hex
from app.contracts.run_state import TERMINAL_STATES, RunState
from app.db.models import (
    Approval,
    BudgetReservation,
    EvidencePassage,
    PlanVersion,
    ReportExport,
    ReportVersion,
    ReviewFindingRow,
    Run,
    RunEvent,
    RunJob,
    Source,
    User,
)
from app.db.models import Brief as BriefRow
from app.db.session import get_sessionmaker
from app.errors import NotFound
from app.policy.permissions import Action
from app.services.exports import export_report
from app.services.runs import (
    cancel_run,
    create_run,
    decide,
    edit_plan,
    get_run,
    latest_artifact,
    retry_run,
    run_access,
)
from app.storage import get_object_store

router = APIRouter(prefix="/api/v1", tags=["runs"])

IdempotencyKey = Annotated[
    str, StringConstraints(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
]


class RunCreate(BaseModel):
    workspace_id: uuid.UUID
    brief: BriefSpec


class RunSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    state: str
    topic: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class JobOut(BaseModel):
    state: str
    waiting_for: str | None
    attempts: int
    wait_deadline_at: datetime | None
    last_error: str | None


class ArtifactOut(BaseModel):
    version: int
    digest: str
    created_at: datetime
    body: dict[str, Any]
    author: str = "agent"
    generation: dict[str, Any] | None = None


class PendingDecision(BaseModel):
    kind: Literal["plan", "report"]
    version: int
    digest: str


class DecisionOut(BaseModel):
    id: uuid.UUID
    kind: str
    version: int
    decision: str
    comment: str | None
    decided_by: str
    decided_at: datetime


class RunDetail(RunSummary):
    brief: dict[str, Any]
    deadline_at: datetime
    outcome_reason: str | None
    job: JobOut
    pending_decision: PendingDecision | None
    plan: ArtifactOut | None
    report: ArtifactOut | None
    decisions: list[DecisionOut]


class EventOut(BaseModel):
    id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class DecisionIn(BaseModel):
    version: int = Field(ge=1)
    digest: Sha256Hex
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class EvidenceOut(BaseModel):
    evidence_id: str
    task_id: str
    locator: str | None
    text: str
    text_sha256: str
    source_id: str
    source_title: str | None
    source_url: str | None
    source_kind: str
    published_on: str | None
    retrieved_at: datetime


def _summary(run: Run, topic: str, creator: str) -> RunSummary:
    return RunSummary(
        id=run.id,
        workspace_id=run.workspace_id,
        state=run.state,
        topic=topic,
        created_by=creator,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _artifact(row: PlanVersion | ReportVersion | None) -> ArtifactOut | None:
    if row is None:
        return None
    return ArtifactOut(
        version=row.version,
        digest=row.digest,
        created_at=row.created_at,
        body=row.body,
        author=getattr(row, "author", "agent"),
        generation=row.generation,
    )


@router.post("/runs", status_code=201, response_model=RunDetail)
def create(
    body: RunCreate,
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    principal: CurrentPrincipal,
    db: DbSession,
    settings: AppSettings,
    response: Response,
) -> RunDetail:
    result = create_run(
        db,
        principal,
        workspace_id=body.workspace_id,
        brief=body.brief,
        idempotency_key=idempotency_key,
        settings=settings,
    )
    if not result.created:
        response.status_code = 200
    return _detail(db, result.run)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    workspace_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
) -> list[RunSummary]:
    check_workspace_access(db, principal, workspace_id, Action.RUN_READ)
    query = (
        select(Run, BriefRow.body["topic"].astext, User.display_name)
        .join(BriefRow, BriefRow.id == Run.brief_id)
        .join(User, User.id == Run.created_by)
        .where(Run.workspace_id == workspace_id)
        .order_by(Run.created_at.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(Run.created_at < before)
    return [_summary(run, topic, creator) for run, topic, creator in db.execute(query).all()]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_detail(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> RunDetail:
    run, _ = get_run(db, principal, run_id, Action.RUN_READ)
    return _detail(db, run)


def _detail(db: DbSession, run: Run) -> RunDetail:
    brief = db.get(BriefRow, run.brief_id)
    creator = db.get(User, run.created_by)
    job = db.get(RunJob, run.id)
    assert brief is not None
    assert creator is not None
    assert job is not None
    plan, report = latest_artifact(db, run.id, "plan"), latest_artifact(db, run.id, "report")
    pending = None
    if job.state == "WAITING" and job.waiting_for in ("plan", "report"):
        artifact = plan if job.waiting_for == "plan" else report
        if artifact is not None:
            pending = PendingDecision(
                kind=job.waiting_for,
                version=artifact.version,
                digest=artifact.digest,
            )
    decisions = db.execute(
        select(Approval, User.display_name)
        .join(User, User.id == Approval.decided_by)
        .where(Approval.run_id == run.id)
        .order_by(Approval.decided_at)
    ).all()
    return RunDetail(
        **_summary(run, brief.body["topic"], creator.display_name).model_dump(),
        brief=brief.body,
        deadline_at=run.deadline_at,
        outcome_reason=run.outcome_reason,
        job=JobOut(
            state=job.state,
            waiting_for=job.waiting_for,
            attempts=job.attempts,
            wait_deadline_at=job.wait_deadline_at,
            last_error=job.last_error,
        ),
        pending_decision=pending,
        plan=_artifact(plan),
        report=_artifact(report),
        decisions=[
            DecisionOut(
                id=a.id,
                kind=a.artifact_kind,
                version=a.artifact_version,
                decision=a.decision,
                comment=a.comment,
                decided_by=name,
                decided_at=a.decided_at,
            )
            for a, name in decisions
        ],
    )


@router.get("/runs/{run_id}/plans/{version}", response_model=ArtifactOut)
def get_plan(run_id: uuid.UUID, version: int, principal: CurrentPrincipal, db: DbSession) -> ArtifactOut:
    get_run(db, principal, run_id, Action.RUN_READ)
    artifact = _artifact(db.get(PlanVersion, (run_id, version)))
    if artifact is None:
        raise NotFound("Plan version not found")
    return artifact


class PlanEditIn(BaseModel):
    base_version: int = Field(ge=1)
    plan: PlanSpec


@router.put(
    "/runs/{run_id}/plan", response_model=ArtifactOut, dependencies=[Depends(run_access(Action.PLAN_DECIDE))]
)
def edit_plan_route(
    run_id: uuid.UUID, body: PlanEditIn, principal: CurrentPrincipal, db: DbSession
) -> ArtifactOut:
    """Save an edited plan as a new version (it must then be approved by version and digest)."""
    artifact = _artifact(edit_plan(db, principal, run_id, base_version=body.base_version, plan=body.plan))
    assert artifact is not None
    return artifact


@router.post(
    "/runs/{run_id}/plan-decisions",
    response_model=DecisionOut,
    status_code=201,
    dependencies=[Depends(run_access(Action.PLAN_DECIDE))],
)
def plan_decision(
    run_id: uuid.UUID, body: DecisionIn, principal: CurrentPrincipal, db: DbSession
) -> DecisionOut:
    return _decision_out(
        db,
        principal,
        decide(
            db,
            principal,
            run_id,
            kind="plan",
            version=body.version,
            digest=body.digest,
            decision=body.decision,
            comment=body.comment,
        ),
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunDetail,
    dependencies=[Depends(run_access(Action.RUN_CANCEL))],
)
def cancel(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> RunDetail:
    """Idempotent. Waiting or queued runs cancel immediately; running ones stop at the next
    step boundary (state CANCEL_REQUESTED until the worker confirms)."""
    return _detail(db, cancel_run(db, principal, run_id))


@router.post(
    "/runs/{run_id}/retry",
    response_model=RunDetail,
    dependencies=[Depends(run_access(Action.RUN_RETRY))],
)
def retry(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> RunDetail:
    """Resume a failed run from its last checkpoint (bounded number of manual retries)."""
    return _detail(db, retry_run(db, principal, run_id))


@router.get("/reports/{report_id}/versions/{version}", response_model=ArtifactOut)
def get_report_version(
    report_id: uuid.UUID, version: int, principal: CurrentPrincipal, db: DbSession
) -> ArtifactOut:
    """A run has exactly one report; its id is the run id."""
    get_run(db, principal, report_id, Action.RUN_READ)
    artifact = _artifact(db.get(ReportVersion, (report_id, version)))
    if artifact is None:
        raise NotFound("Report version not found")
    return artifact


@router.post(
    "/reports/{report_id}/decisions",
    response_model=DecisionOut,
    status_code=201,
    dependencies=[Depends(run_access(Action.REPORT_DECIDE, param="report_id"))],
)
def report_decision(
    report_id: uuid.UUID, body: DecisionIn, principal: CurrentPrincipal, db: DbSession
) -> DecisionOut:
    return _decision_out(
        db,
        principal,
        decide(
            db,
            principal,
            report_id,
            kind="report",
            version=body.version,
            digest=body.digest,
            decision=body.decision,
            comment=body.comment,
        ),
    )


def _decision_out(db: DbSession, principal: Principal, approval: Approval) -> DecisionOut:
    return DecisionOut(
        id=approval.id,
        kind=approval.artifact_kind,
        version=approval.artifact_version,
        decision=approval.decision,
        comment=approval.comment,
        decided_by=principal.display_name,
        decided_at=approval.decided_at,
    )


class FindingOut(BaseModel):
    finding_id: str
    severity: str
    category: str
    source: Literal["deterministic", "model"]
    claim_ids: list[str]
    evidence_ids: list[str]
    requested_action: str


class ReviewRoundOut(BaseModel):
    report_version: int
    review_round: int
    outcome: str
    next: str
    reviewed_at: datetime
    findings: list[FindingOut]


@router.get("/runs/{run_id}/reviews", response_model=list[ReviewRoundOut])
def list_reviews(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> list[ReviewRoundOut]:
    """Review rounds in order, each with its persisted findings (most severe first)."""
    get_run(db, principal, run_id, Action.RUN_READ)
    events = db.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.event_type == "review_completed")
        .order_by(RunEvent.id)
    ).all()
    rows = db.scalars(select(ReviewFindingRow).where(ReviewFindingRow.run_id == run_id)).all()
    order = {"blocker": 0, "major": 1, "minor": 2}
    by_version: dict[int, list[FindingOut]] = {}
    for row in sorted(rows, key=lambda r: (order.get(r.severity, 3), r.finding_id)):
        by_version.setdefault(row.report_version, []).append(
            FindingOut.model_validate(row, from_attributes=True)
        )
    rounds: dict[int, ReviewRoundOut] = {}
    for event in events:
        version = int(event.payload["report_version"])
        # A re-executed reviewer node may log twice; the first event per version stands.
        rounds.setdefault(
            version,
            ReviewRoundOut(
                report_version=version,
                review_round=int(event.payload["round"]),
                outcome=str(event.payload["outcome"]),
                next=str(event.payload["next"]),
                reviewed_at=event.created_at,
                findings=by_version.get(version, []),
            ),
        )
    return list(rounds.values())


class ExportOut(BaseModel):
    id: uuid.UUID
    report_version: int
    report_digest: str
    kind: str
    content_sha256: str
    created_by: str
    created_at: datetime


@router.post(
    "/reports/{report_id}/versions/{version}/export",
    response_class=Response,
    dependencies=[Depends(run_access(Action.RUN_READ, param="report_id"))],
    responses={200: {"content": {"text/markdown": {}}}},
)
def export_report_version(
    report_id: uuid.UUID, version: int, principal: CurrentPrincipal, db: DbSession
) -> Response:
    """Render, store, and download a Markdown export. POST because it records an export
    (CSRF-protected); approved only if a human approved this exact version and digest."""
    run, _ = get_run(db, principal, report_id, Action.RUN_READ)
    exported = export_report(db, get_object_store(), run=run, version=version, user_id=principal.user_id)
    return Response(
        exported.content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"',
            "X-Content-Type-Options": "nosniff",
            "X-Export-Kind": exported.export.kind,
            "X-Content-SHA256": exported.export.content_sha256,
        },
    )


@router.get("/runs/{run_id}/exports", response_model=list[ExportOut])
def list_exports(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> list[ExportOut]:
    get_run(db, principal, run_id, Action.RUN_READ)
    rows = db.execute(
        select(ReportExport, User.display_name)
        .join(User, User.id == ReportExport.created_by)
        .where(ReportExport.run_id == run_id)
        .order_by(ReportExport.created_at.desc())
    ).all()
    return [
        ExportOut(
            id=e.id,
            report_version=e.report_version,
            report_digest=e.report_digest,
            kind=e.kind,
            content_sha256=e.content_sha256,
            created_by=name,
            created_at=e.created_at,
        )
        for e, name in rows
    ]


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(
    run_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
) -> list[EvidenceOut]:
    """FR-05: evidence passages with provenance, scoped to an authorized run. `q` ranks
    passages by full-text relevance within this run only."""
    get_run(db, principal, run_id, Action.RUN_READ)
    query = (
        select(EvidencePassage, Source)
        .join(
            Source,
            (Source.run_id == EvidencePassage.run_id) & (Source.source_id == EvidencePassage.source_id),
        )
        .where(EvidencePassage.run_id == run_id)
    )
    if q:
        tsquery = func.websearch_to_tsquery(text("'english'"), q)
        query = query.where(EvidencePassage.tsv.op("@@")(tsquery)).order_by(
            func.ts_rank_cd(EvidencePassage.tsv, tsquery).desc(), EvidencePassage.evidence_id
        )
    else:
        query = query.order_by(EvidencePassage.task_id, EvidencePassage.evidence_id)
    return [
        EvidenceOut(
            evidence_id=e.evidence_id,
            task_id=e.task_id,
            locator=e.locator,
            text=e.text,
            text_sha256=e.text_sha256,
            source_id=s.source_id,
            source_title=s.title,
            source_url=s.url,
            source_kind=s.kind,
            published_on=s.published_on,
            retrieved_at=s.retrieved_at,
        )
        for e, s in db.execute(query).all()
    ]


class SourceOut(BaseModel):
    source_id: str
    kind: str
    url: str | None
    upload_id: uuid.UUID | None
    title: str | None
    fetch_status: str
    failure_reason: str | None
    retrieved_at: datetime
    published_on: str | None
    content_sha256: str | None
    passages: int


@router.get("/runs/{run_id}/sources", response_model=list[SourceOut])
def list_sources(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> list[SourceOut]:
    """Every source the run touched, including failed fetches (which are never citable)."""
    get_run(db, principal, run_id, Action.RUN_READ)
    counts = (
        select(EvidencePassage.source_id, func.count().label("n"))
        .where(EvidencePassage.run_id == run_id)
        .group_by(EvidencePassage.source_id)
        .subquery()
    )
    rows = db.execute(
        select(Source, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.source_id == Source.source_id)
        .where(Source.run_id == run_id)
        .order_by(Source.fetch_status.desc(), Source.retrieved_at)
    ).all()
    return [
        SourceOut(
            source_id=s.source_id,
            kind=s.kind,
            url=s.url,
            upload_id=s.upload_id,
            title=s.title,
            fetch_status=s.fetch_status,
            failure_reason=s.failure_reason,
            retrieved_at=s.retrieved_at,
            published_on=s.published_on,
            content_sha256=s.content_sha256,
            passages=n,
        )
        for s, n in rows
    ]


class UsageLine(BaseModel):
    step: str
    kind: str
    calls: int
    estimated: Decimal
    actual: Decimal | None
    input_tokens: int
    output_tokens: int


class UsageOut(BaseModel):
    currency: str
    budget: Decimal
    committed: Decimal
    reconciled: Decimal
    outstanding: Decimal
    uncertain: Decimal
    price_schedules: list[str]
    lines: list[UsageLine]
    note: str


@router.get("/runs/{run_id}/usage", response_model=UsageOut)
def run_usage(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> UsageOut:
    """FR-09: estimated vs reconciled cost. Estimated accounting, not a provider billing cap."""
    run, _ = get_run(db, principal, run_id, Action.RUN_READ)
    brief = db.get(BriefRow, run.brief_id)
    assert brief is not None
    budget = Decimal(str(brief.body["budget"]["max_estimated_cost"]))
    spend = spend_for(db, run_id, budget)
    rows = db.execute(
        select(
            BudgetReservation.step,
            BudgetReservation.kind,
            func.count(),
            func.sum(BudgetReservation.estimated_cost),
            func.sum(BudgetReservation.actual_cost),
            func.coalesce(func.sum(BudgetReservation.usage["input_tokens"].as_integer()), 0),
            func.coalesce(func.sum(BudgetReservation.usage["output_tokens"].as_integer()), 0),
        )
        .where(BudgetReservation.run_id == run_id)
        .group_by(BudgetReservation.step, BudgetReservation.kind)
        .order_by(BudgetReservation.step, BudgetReservation.kind)
    ).all()
    schedules = db.scalars(
        select(BudgetReservation.price_snapshot["schedule_id"].astext)
        .where(BudgetReservation.run_id == run_id)
        .distinct()
    ).all()
    return UsageOut(
        currency=brief.body["budget"].get("currency", "USD"),
        budget=budget,
        committed=spend.committed,
        reconciled=spend.reconciled,
        outstanding=spend.outstanding,
        uncertain=spend.uncertain,
        price_schedules=[s for s in schedules if s],
        lines=[
            UsageLine(
                step=st, kind=k, calls=n, estimated=e or Decimal(0), actual=a, input_tokens=i, output_tokens=o
            )
            for st, k, n, e, a, i, o in rows
        ],
        note=(
            "Estimated from configured price schedules and provider-reported usage; "
            "not a provider billing cap."
        ),
    )


@router.get("/runs/{run_id}/timeline", response_model=list[EventOut])
def timeline(
    run_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[EventOut]:
    get_run(db, principal, run_id, Action.RUN_READ)
    return [_event_out(e) for e in _events_after(db, run_id, after, limit)]


def _events_after(db: DbSession, run_id: uuid.UUID, after: int, limit: int) -> list[RunEvent]:
    return list(
        db.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.id > after)
            .order_by(RunEvent.id)
            .limit(limit)
        )
    )


def _event_out(event: RunEvent) -> EventOut:
    return EventOut(id=event.id, type=event.event_type, payload=event.payload, created_at=event.created_at)


@router.get("/runs/{run_id}/events", response_class=StreamingResponse)
async def stream_events(
    run_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    settings: AppSettings,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """FR-10: server-sent events with replay. Reconnecting with Last-Event-ID (sent
    automatically by EventSource) resumes after the last delivered event, so committed events
    are never lost. Access is re-checked on every poll."""
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    def poll(position: int) -> tuple[list[EventOut], bool]:
        with get_sessionmaker()() as db:
            run, _ = get_run(db, principal, run_id, Action.RUN_READ)
            events = [_event_out(e) for e in _events_after(db, run_id, position, 200)]
            return events, RunState(run.state) in TERMINAL_STATES

    await run_in_threadpool(poll, cursor)  # authorize before the 200 response starts

    async def generate() -> AsyncIterator[str]:
        position, idle = cursor, 0
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            try:
                events, terminal = await run_in_threadpool(poll, position)
            except NotFound:
                yield 'event: end\ndata: {"reason": "access revoked"}\n\n'
                return
            for event in events:
                position = event.id
                data = json.dumps(event.model_dump(mode="json"))
                yield f"id: {event.id}\nevent: run_event\ndata: {data}\n\n"
            if terminal and not events:
                yield 'event: end\ndata: {"reason": "terminal"}\n\n'
                return
            idle = 0 if events else idle + 1
            if idle and idle % max(1, int(15 / settings.sse_poll_seconds)) == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(settings.sse_poll_seconds)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
