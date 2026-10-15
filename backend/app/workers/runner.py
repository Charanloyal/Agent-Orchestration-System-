"""Worker process: claim a run, reconcile, advance the graph, then wait, finish, or fail.

    python -m app.workers.runner            # poll forever
    python -m app.workers.runner --once     # one pass (tests, cron-style use)

Execution is at least once (ADR 0008). Only TransientError is retried, with bounded
exponential backoff and jitter; deterministic failures end the run visibly.
"""

import argparse
import logging
import random
import signal
import threading
import uuid
from types import FrameType
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import AgentSuite
from app.agents.fake import fake_agents
from app.config import Settings, get_settings
from app.contracts import Brief as BriefSpec
from app.contracts.run_state import RunState
from app.db.models import Brief, Run
from app.db.session import get_sessionmaker
from app.observability.logging import configure_logging
from app.providers.search import FakeSearch, SearchProvider
from app.services.events import append_event, set_run_state
from app.workers import jobs
from app.workers.checkpointer import FencedPostgresSaver, checkpoint_connection, setup_checkpointer
from app.workers.jobs import Lease, StaleOwner
from app.workflow.context import RunContext
from app.workflow.errors import StepFailed, TransientError
from app.workflow.graph import build_graph

log = logging.getLogger("aos.worker")

WAIT_STATES = {"plan": RunState.AWAITING_PLAN_APPROVAL, "report": RunState.AWAITING_REPORT_APPROVAL}


def build_agents(settings: Settings) -> AgentSuite:
    if settings.agent_mode == "fake":
        return fake_agents()
    raise NotImplementedError("LLM agents arrive in M6")


def build_search(settings: Settings) -> SearchProvider:
    return FakeSearch()


class Heartbeat(threading.Thread):
    """Extends the lease while a pass runs. On rejection, marks the context dead so the next
    fenced write fails fast instead of doing more work for a run it no longer owns."""

    def __init__(self, ctx: RunContext) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{ctx.run_id}")
        self.ctx = ctx
        self.stop = threading.Event()

    def run(self) -> None:
        interval = self.ctx.settings.worker_heartbeat_seconds
        while not self.stop.wait(interval):
            try:
                jobs.heartbeat(self.ctx.sm, self.ctx.lease, self.ctx.settings.worker_lease_seconds)
            except StaleOwner:
                log.warning("lease lost", extra={"run_id": str(self.ctx.run_id)})
                self.ctx.alive.clear()
                return
            except Exception:
                log.exception("heartbeat error", extra={"run_id": str(self.ctx.run_id)})


def _load_context(
    settings: Settings, sm: sessionmaker[Session], lease: Lease, agents: AgentSuite, search: SearchProvider
) -> RunContext:
    with sm() as session:
        run, brief = session.execute(
            select(Run, Brief).join(Brief, Brief.id == Run.brief_id).where(Run.id == lease.run_id)
        ).one()
    return RunContext(
        settings, sm, lease, run.workspace_id, BriefSpec.model_validate(brief.body), agents, search
    )


def process_one(
    settings: Settings | None = None,
    *,
    worker_id: str | None = None,
    run_id: uuid.UUID | None = None,
    agents: AgentSuite | None = None,
    search: SearchProvider | None = None,
) -> str:
    settings = settings or get_settings()
    sm = get_sessionmaker()
    worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    lease = jobs.claim(sm, worker_id, settings.worker_lease_seconds, run_id)
    if lease is None:
        return "no_job"
    ctx = _load_context(
        settings, sm, lease, agents or build_agents(settings), search or build_search(settings)
    )
    heartbeat = Heartbeat(ctx)
    heartbeat.start()
    log_extra = {"run_id": str(lease.run_id), "worker": worker_id, "token": lease.token}
    try:
        with ctx.fenced() as session:
            abandoned = jobs.abandon_unfinished_tool_executions(session, lease)
            if abandoned:
                append_event(
                    session,
                    lease.run_id,
                    ctx.workspace_id,
                    "tool_calls_abandoned",
                    {"count": abandoned, "note": "may have executed and incurred cost"},
                )
        outcome = _advance(ctx)
        log.info("pass finished", extra={**log_extra, "outcome": outcome})
        return outcome
    except StaleOwner:
        log.warning("superseded by another worker; no further writes", extra=log_extra)
        return "stale"
    except TransientError as exc:
        return _retry_or_fail(ctx, exc)
    except StepFailed as exc:
        _fail(ctx, exc.step, exc.reason)
        return "failed"
    except Exception as exc:
        log.exception("unexpected worker error", extra=log_extra)
        _fail(ctx, "worker", f"internal error ({type(exc).__name__})")
        return "failed"
    finally:
        heartbeat.stop.set()


def _advance(ctx: RunContext) -> str:
    with checkpoint_connection(ctx.settings) as conn:
        saver = FencedPostgresSaver(conn, run_id=ctx.run_id, fencing_token=ctx.lease.token)
        graph = build_graph(ctx, saver)
        config: Any = {"configurable": {"thread_id": str(ctx.run_id)}}

        # Reconcile dispatch state (run_jobs) with graph progress (checkpoints).
        snapshot = graph.get_state(config)
        graph_input: Any
        if snapshot.created_at is None:
            graph_input = {}
        elif snapshot.interrupts:
            if ctx.lease.resume_payload is None:
                # Crashed after the interrupt was checkpointed but before the wait was recorded.
                return _release_to_wait(ctx, snapshot.interrupts[0].value["kind"])
            graph_input = Command(resume=ctx.lease.resume_payload)
        elif snapshot.next:
            graph_input = None  # continue from the last committed checkpoint
        else:
            return _complete(ctx)

        graph.invoke(graph_input, config, durability="sync")

        snapshot = graph.get_state(config)
        if snapshot.interrupts:
            return _release_to_wait(ctx, snapshot.interrupts[0].value["kind"])
        if snapshot.next:
            raise RuntimeError(f"graph stopped with pending nodes {snapshot.next}")
        return _complete(ctx)


def _release_to_wait(ctx: RunContext, kind: str) -> str:
    with ctx.fenced() as session:
        set_run_state(session, ctx.run_id, WAIT_STATES[kind])
        jobs.release_to_wait(session, ctx.lease, kind, ctx.settings.approval_ttl_hours)
    return f"waiting_{kind}"


def _complete(ctx: RunContext) -> str:
    with ctx.fenced() as session:
        jobs.mark_done(session, ctx.lease)
    return "done"


def _fail(ctx: RunContext, step: str, reason: str) -> None:
    try:
        with ctx.fenced() as session:
            set_run_state(session, ctx.run_id, RunState.FAILED, f"{step}: {reason}")
            append_event(
                session, ctx.run_id, ctx.workspace_id, "step_failed", {"step": step, "reason": reason[:500]}
            )
            jobs.mark_failed(session, ctx.lease, f"{step}: {reason}")
    except StaleOwner:
        log.warning("could not record failure: lease superseded", extra={"run_id": str(ctx.run_id)})


def _retry_or_fail(ctx: RunContext, exc: TransientError) -> str:
    settings = ctx.settings
    if ctx.lease.attempts >= settings.job_max_attempts:
        _fail(ctx, "worker", f"transient errors persisted after {ctx.lease.attempts} attempts")
        return "failed"
    backoff = min(
        settings.retry_backoff_max_seconds,
        settings.retry_backoff_base_seconds * 2 ** (ctx.lease.attempts - 1),
    )
    delay = max(exc.retry_after or 0.0, backoff * random.uniform(0.5, 1.0))
    with ctx.fenced() as session:
        append_event(
            session,
            ctx.run_id,
            ctx.workspace_id,
            "retry_scheduled",
            {"attempt": ctx.lease.attempts, "delay_seconds": round(delay, 1), "reason": str(exc)[:200]},
        )
        jobs.requeue_with_backoff(session, ctx.lease, delay, str(exc))
    return "retry"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.workers.runner")
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    parser.add_argument("--run-id", type=uuid.UUID, help="only claim this run (tests)")
    parser.add_argument("--worker-id")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    setup_checkpointer(settings)
    worker_id = args.worker_id or f"worker-{uuid.uuid4().hex[:8]}"

    if args.once:
        print(process_one(settings, worker_id=worker_id, run_id=args.run_id), flush=True)
        return 0

    stopping = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        log.info("stop requested; finishing current pass", extra={"signal": signum})
        stopping.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    log.info("worker started", extra={"worker": worker_id})
    while not stopping.is_set():
        outcome = process_one(settings, worker_id=worker_id, run_id=args.run_id)
        if outcome == "no_job":
            stopping.wait(settings.worker_poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
