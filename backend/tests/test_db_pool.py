"""G6: database connection pools are settings, sized against the Render plan's limit."""

import pytest

from app.config import Settings
from app.db.session import build_engine

DB = "postgresql://aos:secret@db.internal:5432/aos"


def test_pool_sizes_come_from_settings() -> None:
    engine = build_engine(Settings(database_url=DB, db_pool_size=3, db_max_overflow=1))
    assert engine.pool.size() == 3  # type: ignore[attr-defined]
    assert engine.pool._max_overflow == 1  # type: ignore[attr-defined]


def test_defaults_stay_as_before() -> None:
    settings = Settings(database_url=DB)
    assert (settings.db_pool_size, settings.db_max_overflow) == (10, 10)


@pytest.mark.parametrize("changes", [{"db_pool_size": 0}, {"db_max_overflow": -1}, {"db_pool_size": 51}])
def test_pool_settings_are_bounded(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Settings(database_url=DB, **changes)
