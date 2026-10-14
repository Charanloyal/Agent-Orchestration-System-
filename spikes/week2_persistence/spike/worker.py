"""One worker pass: claim a run, reconcile, advance the graph, then wait, finish, or fail.

Usage (from spikes/week2_persistence):
    python -m spike.worker --run-id <id> --worker-id w1 [--lease-seconds 30]
                           [--crash-at <point>] [--planner-mode valid|invalid_once|invalid_always]
Prints one JSON line: {"outcome": ...}
"""

import argparse
import json

from langgraph.types import Command

from spike.db import connect
from spike.fakes import SchemaRepairExhausted
from spike.fenced_saver import FencedPostgresSaver
from spike.graph import CRASH_POINTS, WorkerContext, build_graph
from spike.leases import abandon_unfinished_tool_executions, claim, complete, fail, release_to_wait


def run_worker(
    run_id: str | None,
    worker_id: str,
    *,
    lease_seconds: float = 30,
    crash_at: str | None = None,
    planner_mode: str = "valid",
) -> str:
    with connect() as conn, connect() as checkpoint_conn:
        lease = claim(conn, worker_id, lease_seconds, run_id)
        if lease is None:
            return "no_job"
        abandon_unfinished_tool_executions(conn, lease)

        saver = FencedPostgresSaver(checkpoint_conn, run_id=lease.run_id, fencing_token=lease.token)
        graph = build_graph(WorkerContext(conn, lease, crash_at, planner_mode), saver)
        config = {"configurable": {"thread_id": lease.run_id}}

        # Reconcile dispatch state (run_jobs) with graph progress (checkpoints).
        snapshot = graph.get_state(config)
        if snapshot.created_at is None:
            graph_input = {"run_id": lease.run_id}
        elif snapshot.interrupts:
            if lease.resume_payload is None:
                # Crashed after the interrupt was checkpointed but before the wait was recorded.
                kind = snapshot.interrupts[0].value["kind"]
                release_to_wait(conn, lease, kind)
                return f"waiting_{kind}"
            graph_input = Command(resume=lease.resume_payload)
        elif snapshot.next:
            graph_input = None  # continue from the last committed checkpoint
        else:
            complete(conn, lease)
            return "done"

        try:
            graph.invoke(graph_input, config, durability="sync")
        except SchemaRepairExhausted as exc:
            fail(conn, lease, "planner", str(exc))
            return "failed"

        snapshot = graph.get_state(config)
        if snapshot.interrupts:
            kind = snapshot.interrupts[0].value["kind"]
            release_to_wait(conn, lease, kind)
            return f"waiting_{kind}"
        if snapshot.next:
            raise RuntimeError(f"graph stopped with pending nodes {snapshot.next}")
        complete(conn, lease)
        return "done"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lease-seconds", type=float, default=30)
    parser.add_argument("--crash-at", choices=sorted(CRASH_POINTS))
    parser.add_argument("--planner-mode", default="valid", choices=["valid", "invalid_once", "invalid_always"])
    args = parser.parse_args()
    outcome = run_worker(
        args.run_id,
        args.worker_id,
        lease_seconds=args.lease_seconds,
        crash_at=args.crash_at,
        planner_mode=args.planner_mode,
    )
    print(json.dumps({"outcome": outcome}), flush=True)


if __name__ == "__main__":
    main()
