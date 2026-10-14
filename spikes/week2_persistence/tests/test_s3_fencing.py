"""S3: lease expiry, fencing tokens, and stale-owner rejection for app and checkpoint writes."""

import threading
import time
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from spike.db import connect
from spike.fenced_saver import FencedPostgresSaver
from spike.leases import StaleOwner, claim, fenced, heartbeat, release_to_wait
from tests.conftest import count


class Counter(TypedDict):
    value: int


def tiny_graph(saver: FencedPostgresSaver):
    builder = StateGraph(Counter)
    builder.add_node("inc", lambda s: {"value": s["value"] + 1})
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)
    return builder.compile(checkpointer=saver)


def checkpoints(conn, run_id: str) -> int:
    return count(conn, "SELECT 1 FROM checkpoints WHERE thread_id = %s", run_id)


def expire_now(conn, run_id: str) -> None:
    conn.execute("UPDATE run_jobs SET lease_expires_at = now() - interval '1 second' WHERE run_id = %s", (run_id,))


def test_concurrent_claims_have_exactly_one_winner(conn, new_run) -> None:
    run_id = new_run()
    barrier = threading.Barrier(5)
    results: list[object] = []

    def contend(n: int) -> None:
        with connect() as c:
            barrier.wait()
            results.append(claim(c, f"w{n}", 30, run_id))

    threads = [threading.Thread(target=contend, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r is not None]
    assert len(winners) == 1 and winners[0].token == 1


def test_real_lease_expiry_allows_takeover_with_higher_token(conn, new_run) -> None:
    run_id = new_run()
    a = claim(conn, "A", 1, run_id)
    assert claim(conn, "B", 30, run_id) is None
    time.sleep(1.5)
    b = claim(conn, "B", 30, run_id)
    assert b is not None and b.token == a.token + 1


def test_stale_owner_app_writes_and_heartbeat_rejected(conn, new_run) -> None:
    run_id = new_run()
    a = claim(conn, "A", 30, run_id)
    heartbeat(conn, a, 30)
    expire_now(conn, run_id)
    b = claim(conn, "B", 30, run_id)

    with pytest.raises(StaleOwner):
        with fenced(conn, a) as cur:
            cur.execute("UPDATE runs SET state = 'FAILED' WHERE run_id = %s", (run_id,))
    with pytest.raises(StaleOwner):
        heartbeat(conn, a, 30)
    assert conn.execute("SELECT state FROM runs WHERE run_id = %s", (run_id,)).fetchone()["state"] == "QUEUED"
    with fenced(conn, b):
        pass


def test_stale_owner_cannot_write_checkpoints(conn, new_run) -> None:
    run_id = new_run()
    a = claim(conn, "A", 30, run_id)
    expire_now(conn, run_id)
    b = claim(conn, "B", 30, run_id)
    config = {"configurable": {"thread_id": run_id}}

    with connect() as cp:
        with pytest.raises(StaleOwner):
            tiny_graph(FencedPostgresSaver(cp, run_id=run_id, fencing_token=a.token)).invoke(
                {"value": 0}, config, durability="sync"
            )
    assert checkpoints(conn, run_id) == 0, "no checkpoint from the stale owner may commit"

    with connect() as cp:
        result = tiny_graph(FencedPostgresSaver(cp, run_id=run_id, fencing_token=b.token)).invoke(
            {"value": 0}, config, durability="sync"
        )
    assert result == {"value": 1}
    assert checkpoints(conn, run_id) > 0


def test_released_lease_cannot_write_checkpoints(conn, new_run) -> None:
    run_id = new_run()
    a = claim(conn, "A", 30, run_id)
    conn.execute("UPDATE runs SET state = 'PLANNING' WHERE run_id = %s", (run_id,))
    release_to_wait(conn, a, "plan")
    with connect() as cp, pytest.raises(StaleOwner):
        tiny_graph(FencedPostgresSaver(cp, run_id=run_id, fencing_token=a.token)).invoke(
            {"value": 0}, {"configurable": {"thread_id": run_id}}, durability="sync"
        )


def test_open_fenced_write_blocks_takeover_until_commit(conn, new_run) -> None:
    run_id = new_run()
    a = claim(conn, "A", 30, run_id)
    expire_now(conn, run_id)
    with connect() as other:
        with fenced(conn, a):
            # A's write is in flight and holds FOR SHARE: the takeover skips the locked row.
            assert claim(other, "B", 30, run_id) is None
        b = claim(other, "B", 30, run_id)
    assert b is not None and b.token == a.token + 1
