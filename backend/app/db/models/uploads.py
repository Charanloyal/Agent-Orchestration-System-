"""Uploaded documents and their full-text-indexed chunks (FR-05, FR-12)."""

import uuid
from typing import Any

from sqlalchemy import Computed, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, new_id


class Upload(CreatedAtMixin, Base):
    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(200), nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer)
    text_chars: Mapped[int] = mapped_column(Integer, nullable=False)


class UploadChunk(Base):
    __tablename__ = "upload_chunks"
    __table_args__ = (
        Index("ix_upload_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_upload_chunks_workspace", "workspace_id"),
    )

    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    locator: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))
