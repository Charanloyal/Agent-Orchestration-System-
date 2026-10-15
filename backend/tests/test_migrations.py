from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.base import Base
from app.db.session import get_engine
from tests.conftest import run_alembic


def test_models_match_migrations(migrated_database: None) -> None:
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations differ; run alembic revision --autogenerate: {diff}"


def test_downgrade_to_base_and_upgrade_again(migrated_database: None) -> None:
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
