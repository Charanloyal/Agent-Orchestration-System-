"""Runs, dispatch jobs, events, immutable artifacts, approvals, and evidence."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.run_state import RunState
from app.db.base import Base, CreatedAtMixin, new_id

RUN_STATES = ", ".join(f"'{s.value}'" for s in RunState)


class Brief(CreatedAtMixin, Base):
    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("workspace_id", "created_by", "idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class Run(CreatedAtMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(f"state IN ({RUN_STATES})", name="state"),
        Index("ix_runs_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("briefs.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_reason: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RunJob(Base):
    """Dispatch only. Graph progress lives in LangGraph checkpoints (ADR 0007/0008)."""

    __tablename__ = "run_jobs"
    __table_args__ = (
        CheckConstraint("state IN ('QUEUED', 'LEASED', 'WAITING', 'DONE', 'FAILED')", name="state"),
        CheckConstraint("waiting_for IS NULL OR waiting_for IN ('plan', 'report')", name="waiting_for"),
        CheckConstraint(
            "(state = 'LEASED') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="lease_consistent",
        ),
        CheckConstraint("(state = 'WAITING') = (waiting_for IS NOT NULL)", name="wait_consistent"),
        Index("ix_run_jobs_claimable", "state", "available_at"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(10), nullable=False)
    waiting_for: Mapped[str | None] = mapped_column(String(10))
    resume_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    wait_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class RunEvent(CreatedAtMixin, Base):
    """Workspace-visible timeline. Structured summaries only: no prompts or source text."""

    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PlanVersion(CreatedAtMixin, Base):
    __tablename__ = "plan_versions"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    author: Mapped[str] = mapped_column(String(10), nullable=False, default="agent")


class ReportVersion(CreatedAtMixin, Base):
    __tablename__ = "report_versions"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "artifact_kind", "artifact_version"),
        CheckConstraint("artifact_kind IN ('plan', 'report')", name="artifact_kind"),
        CheckConstraint("decision IN ('approve', 'reject')", name="decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    artifact_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500))
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ToolExecution(Base):
    """Recorded before an external call and completed after its result commits (ADR 0008)."""

    __tablename__ = "tool_executions"
    __table_args__ = (
        CheckConstraint("status IN ('started', 'succeeded', 'failed', 'abandoned')", name="status"),
        Index("ix_tool_executions_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(60))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Source(CreatedAtMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("kind IN ('web', 'upload', 'corpus')", name="kind"),
        CheckConstraint("fetch_status IN ('fetched', 'failed')", name="fetch_status"),
        Index("ix_sources_run_id", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    upload_id: Mapped[uuid.UUID | None] = mapped_column()
    title: Mapped[str | None] = mapped_column(String(500))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_on: Mapped[str | None] = mapped_column(String(10))
    fetch_status: Mapped[str] = mapped_column(String(10), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class EvidencePassage(CreatedAtMixin, Base):
    __tablename__ = "evidence_passages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "source_id"], ["sources.run_id", "sources.source_id"], ondelete="CASCADE"
        ),
        Index("ix_evidence_passages_run_task", "run_id", "task_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TaskResult(CreatedAtMixin, Base):
    """First committed outcome of a research task. Re-executed nodes skip committed tasks."""

    __tablename__ = "task_results"
    __table_args__ = (CheckConstraint("status IN ('succeeded', 'no_evidence', 'failed')", name="status"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
