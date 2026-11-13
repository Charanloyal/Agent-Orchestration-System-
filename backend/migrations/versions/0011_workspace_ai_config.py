"""workspace AI engine: provider, model and an encrypted API key per workspace (ADR 0029)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-13

Additive: the build at 0010 keeps working on this schema, so it stays in the compatibility
window (ADR 0020).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_ai_configs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("key_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(length=8), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "provider IN ('gemini', 'groq', 'openai')", name=op.f("ck_workspace_ai_configs_provider")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_ai_configs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_workspace_ai_configs_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace_ai_configs")),
    )
    op.execute("INSERT INTO schema_compatibility (code_revision) VALUES ('0011')")


def downgrade() -> None:
    op.execute("DELETE FROM schema_compatibility WHERE code_revision = '0011'")
    op.drop_table("workspace_ai_configs")
