"""Operational tables: rate-limit counters (ADR 0016)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RateLimitCounter(Base):
    """Fixed-window request counters shared by every API process. Keys never contain raw
    IP addresses (they are hashed) or request content."""

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
