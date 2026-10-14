"""PostgresSaver adapter that rejects checkpoint writes from a superseded lease owner.

Verified against langgraph-checkpoint-postgres 3.1.3: `put`, `put_writes`, and
`delete_thread` all write through `self._cursor(pipeline=True)` on the saver's own
autocommit connection, and reads use `self._cursor()` without pipeline. There is no public
hook for running a check in the same transaction as the write, so this adapter overrides
the private `_cursor` method. That is a deliberate, pinned dependency on an internal API:
upgrading the package requires re-running tests/test_s3_fencing.py.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver, _internal
from psycopg import Cursor
from psycopg.rows import DictRow, dict_row

from spike.leases import StaleOwner


class FencedPostgresSaver(PostgresSaver):
    def __init__(self, conn: _internal.Conn, *, run_id: str, fencing_token: int) -> None:
        super().__init__(conn)
        self.run_id = run_id
        self.fencing_token = fencing_token

    @contextmanager
    def _cursor(self, *, pipeline: bool = False) -> Iterator[Cursor[DictRow]]:
        if not pipeline:
            with super()._cursor(pipeline=False) as cur:
                yield cur
            return
        # Write path: one explicit transaction (no pipeline) containing the fence check and
        # the checkpoint statements, so a stale owner's checkpoint can never commit.
        with self.lock, _internal.get_connection(self.conn) as conn:
            with conn.transaction(), conn.cursor(binary=True, row_factory=dict_row) as cur:
                row = cur.execute(
                    "SELECT fencing_token, state FROM run_jobs WHERE run_id = %s FOR SHARE",
                    (self.run_id,),
                ).fetchone()
                if row is None or row["state"] != "LEASED" or row["fencing_token"] != self.fencing_token:
                    raise StaleOwner(
                        f"checkpoint write rejected: run {self.run_id} token {self.fencing_token}"
                    )
                yield cur
