import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import schema_state
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


def test_upgrade_from_the_last_release_keeps_existing_data(migrated_database: None, db: object) -> None:
    """The deployed pilot is at 0008. Upgrading a populated database keeps every row and
    leaves the pilot's members signed-in-able (they are carried into the access list)."""
    run_alembic("downgrade", "0008")
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, email, display_name) VALUES "
                "('00000000-0000-0000-0000-0000000000a1', 'https://idp.test', 'sub-a', "
                "'Ana@Example.org', 'Ana'), "
                "('00000000-0000-0000-0000-0000000000a2', 'https://idp.test', 'sub-b', "
                "'left@example.org', 'Former member')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO workspaces (id, name) VALUES "
                "('00000000-0000-0000-0000-0000000000b1', 'Pilot team')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO memberships (workspace_id, user_id, role) VALUES "
                "('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000a1', "
                "'admin')"
            )
        )
    run_alembic("upgrade", "head")
    with get_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM memberships")) == 1
        assert conn.scalar(text("SELECT count(*) FROM users")) == 2
        revisions = set(conn.scalars(text("SELECT code_revision FROM schema_compatibility")))
        entries = list(conn.execute(text("SELECT email, source FROM access_list_entries")))
    assert {"0009", "0010"} <= revisions
    assert [tuple(e) for e in entries] == [("ana@example.org", "existing_member")], (
        "only current members are carried over; people without a workspace must ask again"
    )


@pytest.fixture
def previous_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the build before the access-model migration (its head is 0009) running
    against today's database: it knows no later revision."""
    known = frozenset(r for r in schema_state.known_revisions() if r <= "0009")
    monkeypatch.setattr(schema_state, "migration_heads", lambda: frozenset({"0009"}))
    monkeypatch.setattr(schema_state, "known_revisions", lambda: known)


def test_previous_build_stays_ready_on_a_newer_compatible_schema(
    client: TestClient, db: object, previous_build: None
) -> None:
    assert client.get("/readyz").status_code == 200, "rollback target must pass the health check"
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM schema_compatibility WHERE code_revision = '0009'"))
    try:
        refused = client.get("/readyz")
        assert refused.status_code == 503
        assert "no longer supports" in refused.json()["error"]["message"]
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO schema_compatibility (code_revision) VALUES ('0009')"))


def test_a_build_is_never_ready_on_an_older_schema(client: TestClient, db: object) -> None:
    run_alembic("downgrade", "0009")
    try:
        response = client.get("/readyz")
        assert response.status_code == 503 and "behind" in response.json()["error"]["message"]
    finally:
        run_alembic("upgrade", "head")


def test_saved_gemini_engines_move_to_gemini_4_hydrogen_once(db: object) -> None:
    run_alembic("downgrade", "0011")
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM workspace_ai_configs"))
            workspace = conn.scalar(
                text("INSERT INTO workspaces (id, name) VALUES (gen_random_uuid(), 'm12') RETURNING id")
            )
            conn.execute(
                text(
                    "INSERT INTO workspace_ai_configs "
                    "(workspace_id, provider, model, key_ciphertext, key_hint) "
                    "VALUES (:w, 'gemini', 'gemini-3.8-flash', 'x', 'abcd')"
                ),
                {"w": workspace},
            )
        run_alembic("upgrade", "head")
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT model, thinking_level FROM workspace_ai_configs WHERE workspace_id = :w"),
                {"w": workspace},
            ).one()
        assert tuple(row) == ("gemini-4-hydrogen", None)
    finally:
        run_alembic("upgrade", "head")
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM workspace_ai_configs"))
            conn.execute(text("DELETE FROM workspaces WHERE name = 'm12'"))
