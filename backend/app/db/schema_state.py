"""Schema version checks shared by readiness (API) and worker start-up."""

from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR


@lru_cache
def migration_heads() -> frozenset[str]:
    """The Alembic head revision(s) this code expects."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return frozenset(ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_heads())


def current_revisions(db: Session) -> frozenset[str]:
    """Revision(s) the database is at. Raises if the database is unreachable or unmigrated."""
    return frozenset(db.scalars(text("SELECT version_num FROM alembic_version")).all())


def schema_is_current(db: Session) -> bool:
    return current_revisions(db) == migration_heads()
