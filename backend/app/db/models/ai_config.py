"""A workspace's own model engine (ADR 0029): provider, model and an encrypted API key."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceAiConfig(Base):
    __tablename__ = "workspace_ai_configs"
    __table_args__ = (
        CheckConstraint("provider IN ('gemini', 'groq', 'openai')", name="provider"),
        CheckConstraint(
            "thinking_level IS NULL OR thinking_level IN ('low', 'medium', 'high', 'xhigh')",
            name="thinking_level",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Fernet token of the API key; never returned by the API. `key_hint` is its last 4 characters.
    key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    # Gemini thinking depth for the main agents; NULL keeps each model's default (migration 0012).
    thinking_level: Mapped[str | None] = mapped_column(String(10))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
