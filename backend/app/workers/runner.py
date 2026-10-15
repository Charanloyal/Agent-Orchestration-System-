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
from dataclasses import replace
from types import FrameType
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import AgentSuite
from app.agents.fake import fake_agents
from app.agents.llm_planner import LlmPlanner
from app.agents.llm_researcher import LlmResearcher
from app.agents.llm_writer_reviewer import LlmReviewer, LlmWriter
from app.billing.meter import BudgetExhausted, MeteredLlm, MeteredSearch
from app.config import Settings, get_settings
from app.contracts import Brief as BriefSpec
from app.contracts.run_state import RunState
from app.db.models import Brief, Run
from app.db.session import get_sessionmaker
from app.observability.logging import configure_logging
from app.observability.tracing import annotate, configure_tracing, span
from app.providers.breaker import BreakerLlm, BreakerSearch
from app.providers.corpus import CorpusSearch
from app.providers.llm import LlmProvider, OpenAICompatibleLlm
from app.providers.search import FakeSearch, SearchProvider
from app.providers.tavily import TavilySearch
from app.services.events import append_event, set_run_state
from app.services.ratelimit import purge_old_windows
from app.tools.fetcher import Fetcher, FetchPolicy, SafeFetcher
from app.workers import jobs
from app.workers.checkpointer import FencedPostgresSaver, checkpoint_connection, setup_checkpointer
from app.workers.jobs import Lease, StaleOwner
from app.workers.maintenance import expire_overdue_waits, reap_exhausted_jobs
from app.workflow.context import RunContext
from app.workflow.errors import RunStopped, StepFailed, TransientError
from app.workflow.graph import build_graph

log = logging.getLogger("aos.worker")

WAIT_STATES = {"plan": RunState.AWAITING_PLAN_APPROVAL, "report": RunState.AWAITING_REPORT_APPROVAL}


def build_agents(settings: Settings, ctx: RunContext, llm: LlmProvider | None = None) -> AgentSuite:
    """Fake agents by default; every role is an LLM agent (metered against the run budget)
    when configured."""
    if settings.agent_mode == "fake" and llm is None:
        return fake_agents()
    base = llm or OpenAICompatibleLlm(settings)
    tokens = settings.llm_max_output_tokens
    return replace(
        fake_agents(),
        planner=LlmPlanner(
            BreakerLlm(MeteredLlm(base, ctx.meter, "planner"), settings), max_output_tokens=tokens
        ),
        researcher=LlmResearcher(
            BreakerLlm(MeteredLlm(base, ctx.meter, "research"), settings), max_output_tokens=min(tokens, 1500)
        ),
        writer=LlmWriter(
            BreakerLlm(MeteredLlm(base, ctx.meter, "writer"), settings), max_output_tokens=tokens
        ),
        reviewer=LlmReviewer(
            BreakerLlm(MeteredLlm(base, ctx.meter, "reviewer"), settings), max_output_tokens=min(tokens, 1500)
        ),
    )


def build_search(settings: Settings) -> SearchProvider:
    if settings.search_provider == "tavily":
        if settings.tavily_api_key is None:
            raise RuntimeError("AOS_SEARCH_PROVIDER=tavily requires AOS_TAVILY_API_KEY")
        return TavilySearch(settings.tavily_api_key)
    if settings.search_provider == "corpus":
        return CorpusSearch(settings.corpus_dir)
    return FakeSearch()


def build_fetcher(settings: Settings) -> Fetcher:
    return SafeFetcher(
        FetchPolicy(max_bytes=settings.fetch_max_bytes, timeout_seconds=settings.fetch_timeout_seconds)
    )


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
    settings: Settings,
    sm: sessionmaker[Session],
    lease: Lease,
    agents: AgentSuite,
    search: SearchProvider,
    fetcher: Fetcher,
) -> RunContext:
    with sm() as session:
        run, brief = session.execute(
            select(Run, Brief).join(Brief, Brief.id == Run.brief_id).where(Run.id == lease.run_id)
        ).one()
    return RunContext(
        settings, sm, lease, run.workspace_id, BriefSpec.model_validate(brief.body), agents, search, fetcher
    )


def process_one(
    settings: Settings | None = None,
    *,
    worker_id: str | None = None,
    run_id: uuid.UUID | None = None,
    agents: AgentSuite | None = None,
    search: SearchProvider | None = None,
    fetcher: Fetcher | None = None,
    llm: LlmProvider | None = None,
) -> str:
    settings = settings or get_settings()
    sm = get_sessionmaker()
    worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    lease = jobs.claim(sm, worker_id, settings.worker_lease_seconds, run_id)
    if lease is None:
        return "no_job"
    ctx = _load_context(
        settings,
        sm,
        lease,
        fake_agents(),
        search or build_search(settings),
        fetcher or build_fetcher(settings),
    )
    ctx.agents = agents or build_agents(settings, ctx, llm)
    ctx.search = BreakerSearch(MeteredSearch(ctx.search, ctx.meter), settings)
    heartbeat = Heartbeat(ctx)
    heartbeat.start()
    try:
        with span(
            "worker.pass",
            run_id=lease.run_id,
            workspace_id=ctx.workspace_id,
            worker=worker_id,
            fencing_token=lease.token,
            attempt=lease.attempts,
        ) as current:
            outcome = _run_pass(ctx, worker_id)
            annotate(current, outcome=outcome)
            return outcome
    finally:
        heartbeat.stop.set()


def _run_pass(ctx: RunContext, worker_id: str) -> str:
    lease = ctx.lease
    log_extra = {"run_id": str(lease.run_id), "worker": worker_id, "token": lease.token}
    try:
        with ctx.fenced() as session:
            abandoned = jobs.abandon_unfinished_tool_executions(session, lease)
            settled = jobs.settle_stale_reservations(session, lease)
            if abandoned or settled:
                append_event(
                    session,
                    lease.run_id,
                    ctx.workspace_id,
                    "tool_calls_abandoned",
                    {
                        "count": abandoned,
                        "reservations": settled,
                        "note": "may have executed and incurred cost",
                    },
                )
        with ctx.fenced() as session:
            ctx.check_continue(session)
        outcome = _advance(ctx)
        log.info("pass finished", extra={**log_extra, "outcome": outcome})
        return outcome
    except StaleOwner:
        log.warning("superseded by another worker; no further writes", extra=log_extra)
        return "stale"
    except RunStopped as exc:
        return _stop(ctx, exc)
    except TransientError as exc:
        return _retry_or_fail(ctx, exc)
    except StepFailed as exc:
        _fail(ctx, exc.step, exc.reason)
        return "failed"
    except BudgetExhausted as exc:
        _needs_attention(ctx, f"Budget exhausted at {exc.step}; work stopped (estimated accounting)")
        return "done"
    except Exception as exc:
        log.exception("unexpected worker error", extra=log_extra)
        _fail(ctx, "worker", f"internal error ({type(exc).__name__})")
        return "failed"


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
    ctx.crash_if("before_release_to_wait")
    with ctx.fenced() as session:
        ctx.check_continue(session)
        set_run_state(session, ctx.run_id, WAIT_STATES[kind])
        jobs.release_to_wait(session, ctx.lease, kind, ctx.settings.approval_ttl_hours)
    return f"waiting_{kind}"


def _complete(ctx: RunContext) -> str:
    with ctx.fenced() as session:
        jobs.mark_done(session, ctx.lease)
    return "done"


def _stop(ctx: RunContext, stop: RunStopped) -> str:
    """Cancellation or deadline observed at a boundary: finish the run without new work."""
    try:
        with ctx.fenced() as session:
            set_run_state(session, ctx.run_id, RunState(stop.target_state), stop.reason)
            jobs.mark_done(session, ctx.lease)
    except StaleOwner:
        log.warning("could not record stop: lease superseded", extra={"run_id": str(ctx.run_id)})
        return "stale"
    return "cancelled" if stop.target_state == RunState.CANCELLED else "expired"


def _needs_attention(ctx: RunContext, reason: str) -> None:
    with ctx.fenced() as session:
        target, why = RunState.NEEDS_ATTENTION, reason
        try:
            ctx.check_continue(session)
        except RunStopped as stop:
            target, why = RunState(stop.target_state), stop.reason
        set_run_state(session, ctx.run_id, target, why)
        jobs.mark_done(session, ctx.lease)


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
    configure_tracing(settings, "aos-worker")
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
    sm = get_sessionmaker()
    while not stopping.is_set():
        try:
            expired = expire_overdue_waits(sm)
            if expired:
                log.info("expired overdue approval waits", extra={"count": expired})
            reaped = reap_exhausted_jobs(sm)
            if reaped:
                log.warning("reaped jobs whose workers kept crashing", extra={"count": reaped})
            purge_old_windows()
        except Exception:
            log.exception("maintenance failed")
        outcome = process_one(settings, worker_id=worker_id, run_id=args.run_id)
        if outcome == "no_job":
            stopping.wait(settings.worker_poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
