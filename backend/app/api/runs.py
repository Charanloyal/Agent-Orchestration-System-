"""Runs API: create (idempotent), list, inspect, timeline, live events (SSE), decisions."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from app.auth.deps import AppSettings, CurrentPrincipal, DbSession, Principal, check_workspace_access
from app.contracts import Brief as BriefSpec
from app.contracts.common import Sha256Hex
from app.contracts.run_state import TERMINAL_STATES, RunState
from app.db.models import (
    Approval,
    EvidencePassage,
    PlanVersion,
    ReportVersion,
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
from app.services.runs import create_run, decide, get_run, latest_artifact

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
    return ArtifactOut(version=row.version, digest=row.digest, created_at=row.created_at, body=row.body)


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


@router.post("/runs/{run_id}/plan-decisions", response_model=DecisionOut, status_code=201)
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


@router.post("/reports/{report_id}/decisions", response_model=DecisionOut, status_code=201)
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


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> list[EvidenceOut]:
    """FR-05: evidence passages with provenance, scoped to an authorized run."""
    get_run(db, principal, run_id, Action.RUN_READ)
    rows = db.execute(
        select(EvidencePassage, Source)
        .join(
            Source,
            (Source.run_id == EvidencePassage.run_id) & (Source.source_id == EvidencePassage.source_id),
        )
        .where(EvidencePassage.run_id == run_id)
        .order_by(EvidencePassage.task_id, EvidencePassage.evidence_id)
    ).all()
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
            published_on=s.published_on,
            retrieved_at=s.retrieved_at,
        )
        for e, s in rows
    ]


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
