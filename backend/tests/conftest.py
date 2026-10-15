"""Shared test configuration.

Database-backed tests run against a dedicated PostgreSQL database (AOS_TEST_DATABASE_URL,
from the environment or backend/.env). Without it they are skipped, never silently passed.
The schema is rebuilt with Alembic once per session and tables are truncated after each test.
"""

import os
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read_env_file() -> dict[str, str]:
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        return {}
    return dict(
        line.strip().split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


TEST_DATABASE_URL = os.environ.get("AOS_TEST_DATABASE_URL") or _read_env_file().get("AOS_TEST_DATABASE_URL")

# Must happen before the app (and its cached settings) is imported anywhere.
os.environ["AOS_ENV"] = "test"
os.environ["AOS_LOG_JSON"] = "false"
os.environ["AOS_PUBLIC_URL"] = "http://testserver"
if TEST_DATABASE_URL:
    os.environ["AOS_DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ.pop("AOS_DATABASE_URL", None)

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.sessions import create_session
from app.config import get_settings
from app.db.base import Base
from app.db.models import Membership, Role, User, Workspace


def run_alembic(*args: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    getattr(command, args[0])(config, *args[1:])


@pytest.fixture(scope="session")
def migrated_database() -> None:
    if not TEST_DATABASE_URL:
        pytest.skip("AOS_TEST_DATABASE_URL not configured (see README: Local PostgreSQL)")
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS lg CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    run_alembic("upgrade", "head")


@pytest.fixture
def db(migrated_database: None) -> Iterator[Session]:
    from app.db.session import get_engine, get_sessionmaker

    with get_sessionmaker()() as session:
        yield session
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@dataclass
class LoggedIn:
    user: User
    csrf: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def make(name: str = "User") -> User:
        slug = uuid.uuid4().hex[:8]
        user = User(
            oidc_issuer="https://issuer.test",
            oidc_subject=f"sub-{slug}",
            email=f"{name.lower().replace(' ', '.')}.{slug}@example.test",
            display_name=name,
        )
        db.add(user)
        db.commit()
        return user

    return make


@pytest.fixture
def make_workspace(db: Session) -> Callable[..., Workspace]:
    def make(name: str = "Workspace", members: dict[User, Role] | None = None) -> Workspace:
        workspace = Workspace(name=name)
        db.add(workspace)
        db.flush()
        for user, role in (members or {}).items():
            db.add(Membership(workspace_id=workspace.id, user_id=user.id, role=role))
        db.commit()
        return workspace

    return make


@pytest.fixture
def login(db: Session, client: TestClient) -> Callable[[User], LoggedIn]:
    """Create a real server-side session for `user` and install its cookie on the client."""

    def do_login(user: User) -> LoggedIn:
        raw, session = create_session(db, user.id, get_settings())
        db.commit()
        client.cookies.clear()
        client.cookies.set(get_settings().session_cookie_name, raw)
        return LoggedIn(user, session.csrf_token)

    return do_login


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


REPO_ROOT = BACKEND_DIR.parent
SAMPLE_BRIEF: dict[str, object] = __import__("json").loads(
    (REPO_ROOT / "eval" / "briefs" / "dev" / "dev-01.json").read_text(encoding="utf-8")
)["brief"]


@pytest.fixture
def checkpointer_ready(migrated_database: None) -> None:
    from app.workers.checkpointer import setup_checkpointer

    setup_checkpointer(get_settings())


@pytest.fixture
def make_run(db: Session) -> Callable[..., uuid.UUID]:
    """Insert a run directly (no worker), waiting for a plan decision on version 1."""
    from app.contracts import Plan, WriterOutput, artifact_digest
    from app.db.models import Brief, PlanVersion, ReportVersion, Run, RunJob

    def make(workspace: Workspace, user: User) -> uuid.UUID:
        from datetime import UTC, datetime, timedelta

        brief = Brief(
            workspace_id=workspace.id,
            created_by=user.id,
            body=SAMPLE_BRIEF,
            idempotency_key=uuid.uuid4().hex,
            request_sha256="0" * 64,
        )
        db.add(brief)
        db.flush()
        run = Run(
            workspace_id=workspace.id,
            brief_id=brief.id,
            created_by=user.id,
            state="AWAITING_PLAN_APPROVAL",
            deadline_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(run)
        db.flush()
        plan = Plan.model_validate(
            {
                "plan_version": 1,
                "source_strategy": "s",
                "outline": [{"section_id": "s", "title": "S", "purpose": "p"}],
                "tasks": [
                    {
                        "task_id": "t1",
                        "question": "q",
                        "tools": ["web_search"],
                        "expected_evidence": "e",
                        "section_ids": ["s"],
                    }
                ],
            }
        )
        report = WriterOutput.model_validate(
            {
                "report_version": 1,
                "plan_version": 1,
                "sections": [
                    {
                        "section_id": "s",
                        "title": "S",
                        "claims": [{"claim_id": "c1", "kind": "unknown", "text": "t"}],
                    }
                ],
            }
        )
        db.add_all(
            [
                RunJob(run_id=run.id, state="WAITING", waiting_for="plan"),
                PlanVersion(
                    run_id=run.id, version=1, digest=artifact_digest(plan), body=plan.model_dump(mode="json")
                ),
                ReportVersion(
                    run_id=run.id,
                    version=1,
                    plan_version=1,
                    digest=artifact_digest(report),
                    body=report.model_dump(mode="json"),
                ),
            ]
        )
        db.commit()
        return run.id

    return make


@pytest.fixture(scope="session")
def dev_issuer() -> Iterator[str]:
    """The real dev OIDC issuer, served by uvicorn on a free localhost port."""
    import uvicorn

    from devtools.dev_oidc import create_dev_issuer

    port = free_port()
    issuer = f"http://127.0.0.1:{port}"
    app = create_dev_issuer(
        issuer,
        client_id="aos-local",
        redirect_uris=["http://testserver/api/v1/auth/callback"],
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("dev issuer did not start")
        time.sleep(0.05)
    yield issuer
    server.should_exit = True
    thread.join(timeout=5)
