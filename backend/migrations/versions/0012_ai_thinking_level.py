"""workspace AI engine: thinking depth; saved Gemini models upgraded to Gemini 4 Hydrogen (ADR 0029)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13

Additive: a nullable column, so the build at 0011 keeps working on this schema and stays in
the compatibility window (ADR 0020). Saved Gemini engines on a retired or superseded model
(2.x, 3.0 to 3.8 Flash) move to `gemini-4-hydrogen` once, here; an admin who later chooses
3.8 Flash on purpose keeps it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADED = (
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
)


def upgrade() -> None:
    op.add_column("workspace_ai_configs", sa.Column("thinking_level", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f("ck_workspace_ai_configs_thinking_level"),
        "workspace_ai_configs",
        "thinking_level IS NULL OR thinking_level IN ('low', 'medium', 'high', 'xhigh')",
    )
    op.execute(
        sa.text(
            "UPDATE workspace_ai_configs SET model = 'gemini-4-hydrogen' "
            "WHERE provider = 'gemini' AND model IN :models"
        ).bindparams(sa.bindparam("models", value=UPGRADED, expanding=True))
    )
    op.execute("INSERT INTO schema_compatibility (code_revision) VALUES ('0012')")


def downgrade() -> None:
    op.execute("DELETE FROM schema_compatibility WHERE code_revision = '0012'")
    op.drop_constraint(op.f("ck_workspace_ai_configs_thinking_level"), "workspace_ai_configs", type_="check")
    op.drop_column("workspace_ai_configs", "thinking_level")
