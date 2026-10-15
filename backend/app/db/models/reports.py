"""Review findings per report version and round, and export records (FR-07, FR-11)."""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, new_id


class ReviewFindingRow(CreatedAtMixin, Base):
    __tablename__ = "review_findings"
    __table_args__ = (
        CheckConstraint("severity IN ('blocker', 'major', 'minor')", name="severity"),
        CheckConstraint("source IN ('deterministic', 'model')", name="source"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    report_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(15), nullable=False)
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    requested_action: Mapped[str] = mapped_column(String(500), nullable=False)


class ReportExport(CreatedAtMixin, Base):
    __tablename__ = "report_exports"
    __table_args__ = (
        CheckConstraint("kind IN ('approved', 'draft')", name="kind"),
        Index("ix_report_exports_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    report_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
