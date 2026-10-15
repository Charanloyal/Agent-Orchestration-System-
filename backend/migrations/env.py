"""Alembic environment. The database URL comes from application settings (AOS_DATABASE_URL),
never from alembic.ini, so no credentials live in version control."""

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.db.models  # noqa: F401  (registers all tables on Base.metadata)
from app.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata

# LangGraph owns its checkpoint tables in the "lg" schema; Alembic must not manage them.
EXCLUDED_SCHEMAS = {"lg"}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    schema = getattr(obj, "schema", None)
    return schema not in EXCLUDED_SCHEMAS


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().sqlalchemy_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = engine_from_config(
            {"sqlalchemy.url": get_settings().sqlalchemy_url()},
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with engine.connect() as connection:
            _configure_and_run(connection)
    else:
        _configure_and_run(connectable)


def _configure_and_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
