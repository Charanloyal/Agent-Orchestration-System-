"""Operational tables: rate-limit counters (ADR 0016) and the schema compatibility window
(ADR 0020)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class SchemaCompatibility(CreatedAtMixin, Base):
    """Code revisions (Alembic heads) that may run against this database. Every additive
    migration inserts its own revision and keeps the older rows, so the previous build stays
    ready after a migration and can be rolled back to. A migration that breaks older code
    deletes the rows it invalidates (ADR 0020)."""

    __tablename__ = "schema_compatibility"

    code_revision: Mapped[str] = mapped_column(String(32), primary_key=True)


class RateLimitCounter(Base):
    """Fixed-window request counters shared by every API process. Keys never contain raw
    IP addresses (they are hashed) or request content."""

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
