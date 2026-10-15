"""Estimated-cost ledger: reservations before provider calls, reconciliation after (FR-09)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, new_id

Money = Numeric(12, 6)


class BudgetReservation(CreatedAtMixin, Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint("kind IN ('llm', 'search')", name="kind"),
        CheckConstraint("status IN ('reserved', 'reconciled')", name="status"),
        CheckConstraint("estimated_cost >= 0", name="estimate_non_negative"),
        Index("ix_budget_reservations_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="reserved")
    estimated_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)
    actual_cost: Mapped[Decimal | None] = mapped_column(Money)
    # True when a call failed after it may have reached the provider: it might have been
    # billed, so the estimate is kept as the (conservative) actual.
    uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    price_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
