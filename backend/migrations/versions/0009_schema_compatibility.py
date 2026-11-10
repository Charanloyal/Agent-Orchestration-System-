"""schema_compatibility window (ADR 0020)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-06

Records which code revisions may run against this database. Readiness (API) and worker
start-up accept the schema when it is exactly at the code's head, or when the database is at
a newer revision whose compatibility rows still list the code's head. That lets the previous
build keep serving (and be rolled back to) after an additive migration.

Rules for later migrations (docs/operations/migrations.md):
- additive (new tables, nullable columns, new indexes): insert the new revision, keep the rest;
- breaking for older code (drops, renames, NOT NULL without default): delete the rows of the
  code revisions it breaks, so those builds report not-ready instead of failing at runtime.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schema_compatibility",
        sa.Column("code_revision", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code_revision", name=op.f("pk_schema_compatibility")),
    )
    # Code at 0008 does not know this table and only accepts an exact head match, so the
    # window starts here.
    op.execute("INSERT INTO schema_compatibility (code_revision) VALUES ('0009')")


def downgrade() -> None:
    op.drop_table("schema_compatibility")
