"""Schema version checks shared by readiness (API) and worker start-up (ADR 0020)."""

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR

if TYPE_CHECKING:
    from alembic.script import ScriptDirectory


@lru_cache
def migration_heads() -> frozenset[str]:
    """The Alembic head revision(s) this code expects."""
    return frozenset(_script_directory().get_heads())


@lru_cache
def known_revisions() -> frozenset[str]:
    """Every revision this code ships. A database at one of them, other than the head, is
    behind this build; a database at a revision outside this set is newer."""
    return frozenset(script.revision for script in _script_directory().walk_revisions())


def _script_directory() -> ScriptDirectory:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))


def current_revisions(db: Session) -> frozenset[str]:
    """Revision(s) the database is at. Raises if the database is unreachable or unmigrated."""
    return frozenset(db.scalars(text("SELECT version_num FROM alembic_version")).all())


def supported_code_revisions(db: Session) -> frozenset[str]:
    """Code revisions the database declares compatible; empty before migration 0009."""
    if db.scalar(text("SELECT to_regclass('schema_compatibility')")) is None:
        return frozenset()
    return frozenset(db.scalars(text("SELECT code_revision FROM schema_compatibility")).all())


@dataclass(frozen=True)
class SchemaStatus:
    current: frozenset[str]
    expected: frozenset[str]
    compatible: bool
    reason: str


def schema_status(db: Session) -> SchemaStatus:
    """Ready when the database is exactly at this code's head, or at a *newer* revision that
    still lists this code's head as compatible (the previous build during and after a deploy,
    or after a rollback). Never ready on an older schema. Raises if the database is
    unreachable or unmigrated."""
    current, expected = current_revisions(db), migration_heads()
    if current == expected:
        return SchemaStatus(current, expected, True, "at the code's migration head")
    if current <= known_revisions():
        return SchemaStatus(
            current,
            expected,
            False,
            "Database schema is behind this build's migration head; run `alembic upgrade head`",
        )
    if expected <= supported_code_revisions(db):
        return SchemaStatus(current, expected, True, "newer schema that declares this build compatible")
    return SchemaStatus(
        current,
        expected,
        False,
        "Database schema is newer than this build's migration head and no longer supports it; "
        "deploy a build at or after the database revision",
    )


def schema_is_current(db: Session) -> bool:
    return current_revisions(db) == migration_heads()


def schema_is_compatible(db: Session) -> bool:
    return schema_status(db).compatible
