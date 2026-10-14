"""Connection handling and the spike's application schema."""

import os
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / "backend" / ".env"


def database_url() -> str | None:
    if url := os.environ.get("AOS_DATABASE_URL"):
        return url
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("AOS_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


def connect() -> psycopg.Connection:
    url = database_url()
    if not url:
        raise RuntimeError("AOS_DATABASE_URL is not set (env var or backend/.env)")
    # Same connection settings PostgresSaver.from_conn_string uses.
    return psycopg.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        text PRIMARY KEY,
    workspace_id  text NOT NULL,
    state         text NOT NULL,
    brief         jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Dispatch only. Graph progress lives in LangGraph checkpoints, not here.
CREATE TABLE IF NOT EXISTS run_jobs (
    run_id            text PRIMARY KEY REFERENCES runs(run_id),
    state             text NOT NULL CHECK (state IN ('QUEUED', 'LEASED', 'WAITING', 'DONE', 'FAILED')),
    waiting_for       text CHECK (waiting_for IN ('plan', 'report')),
    resume_payload    jsonb,
    lease_owner       text,
    lease_expires_at  timestamptz,
    fencing_token     bigint NOT NULL DEFAULT 0,
    attempts          int NOT NULL DEFAULT 0,
    max_attempts      int NOT NULL DEFAULT 10,
    available_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((state = 'LEASED') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK ((state = 'WAITING') = (waiting_for IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS plan_versions (
    run_id      text NOT NULL REFERENCES runs(run_id),
    version     int NOT NULL,
    digest      text NOT NULL,
    body        jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, version)
);

CREATE TABLE IF NOT EXISTS report_versions (
    run_id      text NOT NULL REFERENCES runs(run_id),
    version     int NOT NULL,
    digest      text NOT NULL,
    body        jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, version)
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id       text PRIMARY KEY,
    run_id            text NOT NULL REFERENCES runs(run_id),
    artifact_kind     text NOT NULL CHECK (artifact_kind IN ('plan', 'report')),
    artifact_version  int NOT NULL,
    artifact_digest   text NOT NULL,
    decision          text NOT NULL CHECK (decision IN ('approve', 'reject')),
    decided_by        text NOT NULL,
    decided_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, artifact_kind, artifact_version)
);

CREATE TABLE IF NOT EXISTS evidence (
    run_id         text NOT NULL REFERENCES runs(run_id),
    evidence_id    text NOT NULL,
    task_id        text NOT NULL,
    text           text NOT NULL,
    text_sha256    text NOT NULL,
    fencing_token  bigint NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS tool_executions (
    tool_execution_id  text PRIMARY KEY,
    run_id             text NOT NULL REFERENCES runs(run_id),
    task_id            text NOT NULL,
    tool               text NOT NULL,
    status             text NOT NULL CHECK (status IN ('started', 'succeeded', 'failed', 'abandoned')),
    fencing_token      bigint NOT NULL,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz
);

CREATE TABLE IF NOT EXISTS run_events (
    event_id    bigserial PRIMARY KEY,
    run_id      text NOT NULL REFERENCES runs(run_id),
    event_type  text NOT NULL,
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS run_events_by_run ON run_events (run_id, event_id);
"""


def setup_schema() -> None:
    with connect() as conn:
        # prepare_threshold=0 forbids multi-statement strings, so run statements one by one.
        for statement in filter(str.strip, SCHEMA_SQL.split(";")):
            conn.execute(statement)
        PostgresSaver(conn).setup()
