from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings())


def build_engine(settings: Settings) -> Engine:
    """One pool per process (API, worker). Size it with AOS_DB_POOL_SIZE / AOS_DB_MAX_OVERFLOW
    against the database plan's connection limit (docs/operations/deploy-render.md)."""
    return create_engine(
        settings.sqlalchemy_url(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"application_name": "aos-api"},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request. Services commit explicitly."""
    with get_sessionmaker()() as session:
        yield session
