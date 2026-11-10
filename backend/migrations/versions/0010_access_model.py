"""access model: access list, access requests, workspace invitations (ADR 0021)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-06

Additive: the build at 0009 keeps working on this schema, so it stays in the compatibility
window (ADR 0020). Current workspace members are carried into the access list, so switching
a deployment to invite-only sign-in never locks out people who already use it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_list_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source IN ('admin', 'request', 'invitation', 'existing_member', 'seed')",
            name=op.f("ck_access_list_entries_source"),
        ),
        sa.ForeignKeyConstraint(
            ["added_by"],
            ["users.id"],
            name=op.f("fk_access_list_entries_added_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_list_entries")),
        sa.UniqueConstraint("email", name=op.f("uq_access_list_entries_email")),
    )
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied')", name=op.f("ck_access_requests_status")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_access_requests_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_requests")),
    )
    op.create_index(
        "uq_access_requests_pending_email",
        "access_requests",
        ["email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "role IN ('analyst', 'reviewer', 'admin')", name=op.f("ck_workspace_invitations_role")
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
            name=op.f("fk_workspace_invitations_accepted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_workspace_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_invitations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invitations")),
    )
    op.create_index("ix_workspace_invitations_email", "workspace_invitations", ["email"], unique=False)
    op.create_index(
        op.f("ix_workspace_invitations_workspace_id"), "workspace_invitations", ["workspace_id"], unique=False
    )
    op.create_index(
        "uq_workspace_invitations_pending",
        "workspace_invitations",
        ["workspace_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.execute(
        """
        INSERT INTO access_list_entries (id, email, source, note)
        SELECT gen_random_uuid(), lower(u.email), 'existing_member', 'Member before invite-only sign-in'
        FROM users u
        WHERE u.email IS NOT NULL
          AND EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = u.id)
        GROUP BY lower(u.email)
        """
    )
    op.execute("INSERT INTO schema_compatibility (code_revision) VALUES ('0010')")


def downgrade() -> None:
    op.execute("DELETE FROM schema_compatibility WHERE code_revision = '0010'")
    op.drop_index(
        "uq_workspace_invitations_pending",
        table_name="workspace_invitations",
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_index(op.f("ix_workspace_invitations_workspace_id"), table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_email", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
    op.drop_index(
        "uq_access_requests_pending_email",
        table_name="access_requests",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("access_requests")
    op.drop_table("access_list_entries")
