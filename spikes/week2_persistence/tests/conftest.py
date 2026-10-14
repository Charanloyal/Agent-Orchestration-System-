import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest

from spike.db import REPO_ROOT, connect, database_url, setup_schema
from spike.leases import enqueue_run

SPIKE_DIR = Path(__file__).resolve().parents[1]
BRIEF = json.loads((REPO_ROOT / "eval" / "briefs" / "dev" / "dev-01.json").read_text(encoding="utf-8"))["brief"]


@pytest.fixture(scope="session")
def db_schema() -> None:
    if not database_url():
        pytest.skip("AOS_DATABASE_URL not configured; see spikes/week2_persistence/README.md")
    setup_schema()


@pytest.fixture
def conn(db_schema: None) -> Iterator[psycopg.Connection]:
    with connect() as connection:
        yield connection


@pytest.fixture
def new_run(conn: psycopg.Connection) -> Callable[[], str]:
    def make() -> str:
        run_id = uuid.uuid4().hex
        enqueue_run(conn, run_id, "ws-test", BRIEF)
        return run_id

    return make


def run_worker_process(
    run_id: str,
    worker_id: str,
    *,
    crash_at: str | None = None,
    lease_seconds: float = 30,
    planner_mode: str = "valid",
) -> tuple[int, str | None]:
    """Run one worker pass in a separate OS process; state is shared only via PostgreSQL."""
    cmd = [sys.executable, "-m", "spike.worker", "--run-id", run_id, "--worker-id", worker_id,
           "--lease-seconds", str(lease_seconds), "--planner-mode", planner_mode]
    if crash_at:
        cmd += ["--crash-at", crash_at]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SPIKE_DIR), str(REPO_ROOT / "backend")])}
    proc = subprocess.run(cmd, cwd=SPIKE_DIR, env=env, capture_output=True, text=True, timeout=120)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    outcome = json.loads(lines[-1])["outcome"] if lines else None
    if proc.returncode not in (0, 137):
        raise AssertionError(f"worker failed rc={proc.returncode}\n{proc.stderr[-3000:]}")
    return proc.returncode, outcome


def wait_for_lease_expiry(conn: psycopg.Connection, run_id: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = conn.execute(
            "SELECT lease_expires_at < now() AS expired FROM run_jobs WHERE run_id = %s", (run_id,)
        ).fetchone()
        if row["expired"]:
            return
        time.sleep(0.25)
    raise AssertionError("lease did not expire")


def job(conn: psycopg.Connection, run_id: str) -> dict:
    return conn.execute("SELECT * FROM run_jobs WHERE run_id = %s", (run_id,)).fetchone()


def run_state(conn: psycopg.Connection, run_id: str) -> str:
    return conn.execute("SELECT state FROM runs WHERE run_id = %s", (run_id,)).fetchone()["state"]


def latest(conn: psycopg.Connection, table: str, run_id: str) -> dict:
    return conn.execute(
        f"SELECT version, digest FROM {table} WHERE run_id = %s ORDER BY version DESC LIMIT 1", (run_id,)
    ).fetchone()


def count(conn: psycopg.Connection, sql: str, *params: object) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM ({sql}) q", params).fetchone()["n"]


def state_history(conn: psycopg.Connection, run_id: str) -> list[str]:
    rows = conn.execute(
        """SELECT payload->>'to' AS to_state FROM run_events
           WHERE run_id = %s AND event_type = 'state_changed' ORDER BY event_id""",
        (run_id,),
    ).fetchall()
    return [r["to_state"] for r in rows]
