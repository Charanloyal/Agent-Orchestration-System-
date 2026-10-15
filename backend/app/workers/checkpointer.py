"""LangGraph checkpointer bound to the current lease (ADR 0007).

Verified against langgraph-checkpoint-postgres 3.1.3: `put`, `put_writes`, and
`delete_thread` write through the private `_cursor(pipeline=True)`; reads use `_cursor()`.
There is no public hook for a same-transaction check, so this subclass overrides `_cursor`.
Pinned dependency on an internal API: tests/test_worker_fencing.py must pass on upgrade.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver, _internal
from psycopg import Cursor
from psycopg.rows import DictRow, dict_row

from app.config import Settings
from app.workers.jobs import StaleOwner

CHECKPOINT_SCHEMA = "lg"


def checkpoint_connection(settings: Settings) -> psycopg.Connection[DictRow]:
    """Autocommit connection whose search_path is the library-owned checkpoint schema."""
    return psycopg.connect(
        settings.libpq_url(),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=f"-c search_path={CHECKPOINT_SCHEMA}",
        application_name="aos-checkpointer",
    )


def setup_checkpointer(settings: Settings) -> None:
    """Create or upgrade LangGraph's own tables in the `lg` schema (idempotent)."""
    with checkpoint_connection(settings) as conn:
        PostgresSaver(conn).setup()


class FencedPostgresSaver(PostgresSaver):  # type: ignore[misc]  # langgraph is untyped to mypy
    def __init__(self, conn: _internal.Conn, *, run_id: uuid.UUID, fencing_token: int) -> None:
        super().__init__(conn)
        self.run_id = run_id
        self.fencing_token = fencing_token

    @contextmanager
    def _cursor(self, *, pipeline: bool = False) -> Iterator[Cursor[DictRow]]:
        if not pipeline:
            with super()._cursor(pipeline=False) as cur:
                yield cur
            return
        # Write path: one explicit transaction containing the fence check and the checkpoint
        # statements, so a superseded owner's checkpoint can never commit.
        with (
            self.lock,
            _internal.get_connection(self.conn) as conn,
            conn.transaction(),
            conn.cursor(binary=True, row_factory=dict_row) as cur,
        ):
            row = cur.execute(
                "SELECT fencing_token, state FROM public.run_jobs WHERE run_id = %s FOR SHARE",
                (self.run_id,),
            ).fetchone()
            if row is None or row["state"] != "LEASED" or row["fencing_token"] != self.fencing_token:
                raise StaleOwner(f"checkpoint write rejected for run {self.run_id}")
            yield cur
