"""Access model (ADR 0021): the deployment's access list, public access requests, and
workspace invitations. Emails are stored lower-cased."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, new_id
from app.db.models.identity import ROLE_VALUES

ACCESS_SOURCES = ("admin", "request", "invitation", "existing_member", "seed")
REQUEST_STATUSES = ("pending", "approved", "denied")


class AccessListEntry(CreatedAtMixin, Base):
    """A verified email that may sign in even when it is on no allowlist and has no
    invitation. Removing an entry signs the person out (their sessions are revoked)."""

    __tablename__ = "access_list_entries"
    __table_args__ = (
        CheckConstraint(f"source IN ({', '.join(repr(s) for s in ACCESS_SOURCES)})", name="source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AccessRequest(CreatedAtMixin, Base):
    """Someone asking for access from the sign-in page. At most one pending request per email;
    decided requests are removed by retention after AOS_RETENTION_ACCESS_REQUEST_DAYS."""

    __tablename__ = "access_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in REQUEST_STATUSES)})", name="status"),
        Index(
            "uq_access_requests_pending_email",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceInvitation(CreatedAtMixin, Base):
    """An admin's invitation of an email into a workspace with a role. It is accepted
    automatically the first time that verified email signs in before `expires_at`."""

    __tablename__ = "workspace_invitations"
    __table_args__ = (
        CheckConstraint(f"role IN ({ROLE_VALUES})", name="role"),
        Index(
            "uq_workspace_invitations_pending",
            "workspace_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("ix_workspace_invitations_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
