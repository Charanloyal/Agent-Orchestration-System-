"""audit_events append-only trigger (ADR 0018)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03

Audit rows may never be deleted or rewritten by the application. The only UPDATE allowed is
the foreign-key side effect of deleting a user or workspace (ON DELETE SET NULL), which may
null out actor_user_id / workspace_id while every other column stays identical.
A database superuser can still disable triggers; that limitation is documented.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'audit_events is append-only (delete refused)'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NEW.id = OLD.id
               AND NEW.action = OLD.action
               AND NEW.target IS NOT DISTINCT FROM OLD.target
               AND NEW.details = OLD.details
               AND NEW.created_at = OLD.created_at
               AND (NEW.workspace_id IS NOT DISTINCT FROM OLD.workspace_id OR NEW.workspace_id IS NULL)
               AND (NEW.actor_user_id IS NOT DISTINCT FROM OLD.actor_user_id OR NEW.actor_user_id IS NULL)
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'audit_events is append-only (update refused)'
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
