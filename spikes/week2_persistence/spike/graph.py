"""Tiny research workflow graph for testing persistence, interruption, and recovery.

Nodes may run more than once (crash recovery re-executes the interrupted node, and
LangGraph re-executes a node from its start when resuming an `interrupt`). Every side
effect is therefore idempotent and fenced: deterministic keys, ON CONFLICT DO NOTHING,
and "first committed result wins".
"""

import os
import uuid
from dataclasses import dataclass
from typing import TypedDict

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from psycopg.types.json import Jsonb

from app.contracts import (
    Plan,
    PlanPolicy,
    ReviewerOutput,
    RunState,
    WriterOutput,
    artifact_digest,
    enforce_plan_policy,
    route_after_review,
    validate_citations,
)
from app.contracts.common import sha256_hex
from spike import fakes
from spike.approvals import load_approval
from spike.leases import Lease, add_event, fenced, set_run_state

POLICY = PlanPolicy(allowed_tools=frozenset({"web_search", "fetch_url"}), max_tasks=6)

CRASH_POINTS = frozenset(
    {"after_search_before_commit", "after_evidence_commit", "before_writer", "after_report_commit"}
)


class RunGraphState(TypedDict, total=False):
    run_id: str
    plan_version: int
    plan_digest: str
    plan: dict
    plan_decision: str
    evidence_ids: list[str]
    report_version: int
    report_digest: str
    review_round: int
    review_next: str
    report_decision: str


@dataclass
class WorkerContext:
    conn: psycopg.Connection
    lease: Lease
    crash_at: str | None = None
    planner_mode: str = "valid"


class ApprovalMismatch(RuntimeError):
    pass


class CitationCheckFailed(RuntimeError):
    pass


def build_graph(ctx: WorkerContext, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    run_id = ctx.lease.run_id

    def crash_if(point: str) -> None:
        if ctx.crash_at == point:
            os._exit(137)  # abrupt worker death: no cleanup, no finally blocks, no flush

    def transition(target: RunState) -> None:
        with fenced(ctx.conn, ctx.lease) as cur:
            set_run_state(cur, run_id, target)

    def verified_decision(resume: dict, kind: str, version: int, digest: str) -> str:
        approval = load_approval(ctx.conn, resume["approval_id"])
        got = (approval["run_id"], approval["artifact_kind"], approval["artifact_version"], approval["artifact_digest"])
        if got != (run_id, kind, version, digest):
            raise ApprovalMismatch(f"approval does not bind to {kind} v{version} of run {run_id}")
        return approval["decision"]

    def planner(state: RunGraphState) -> RunGraphState:
        transition(RunState.PLANNING)
        version = state.get("plan_version", 0) + 1
        proposed, attempts = fakes.call_structured(
            fakes.planner_model(ctx.planner_mode), Plan, "Plan the research brief."
        )
        # The server, not the model, assigns the version; the policy, not the model, sets limits.
        plan = Plan.model_validate({**proposed.model_dump(mode="json"), "plan_version": version})
        enforce_plan_policy(plan, POLICY)
        with fenced(ctx.conn, ctx.lease) as cur:
            inserted = cur.execute(
                """INSERT INTO plan_versions (run_id, version, digest, body) VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (run_id, version, artifact_digest(plan), Jsonb(plan.model_dump(mode="json"))),
            ).rowcount
            row = cur.execute(
                "SELECT digest, body FROM plan_versions WHERE run_id = %s AND version = %s",
                (run_id, version),
            ).fetchone()
            if inserted:
                add_event(cur, run_id, "plan_proposed", {"version": version, "model_attempts": attempts})
        return {"plan_version": version, "plan_digest": row["digest"], "plan": row["body"]}

    def await_plan(state: RunGraphState) -> RunGraphState:
        resume = interrupt({"kind": "plan", "version": state["plan_version"], "digest": state["plan_digest"]})
        decision = verified_decision(resume, "plan", state["plan_version"], state["plan_digest"])
        return {"plan_decision": decision}

    def research(state: RunGraphState) -> RunGraphState:
        transition(RunState.RESEARCHING)
        plan = Plan.model_validate(state["plan"])
        questions = {t.task_id: t.question for t in plan.tasks}
        for level in plan.execution_order():
            for task_id in level:
                already = ctx.conn.execute(
                    "SELECT 1 FROM evidence WHERE run_id = %s AND task_id = %s LIMIT 1", (run_id, task_id)
                ).fetchone()
                if already:
                    continue  # committed by an earlier owner: do not repeat the external call
                execution_id = uuid.uuid4().hex
                with fenced(ctx.conn, ctx.lease) as cur:
                    cur.execute(
                        """INSERT INTO tool_executions
                               (tool_execution_id, run_id, task_id, tool, status, fencing_token)
                           VALUES (%s, %s, %s, 'web_search', 'started', %s)""",
                        (execution_id, run_id, task_id, ctx.lease.token),
                    )
                passages = fakes.fake_search(task_id, questions[task_id])
                crash_if("after_search_before_commit")
                with fenced(ctx.conn, ctx.lease) as cur:
                    for n, text in enumerate(passages, 1):
                        cur.execute(
                            """INSERT INTO evidence
                                   (run_id, evidence_id, task_id, text, text_sha256, fencing_token)
                               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                            (run_id, f"ev-{task_id}-{n}", task_id, text, sha256_hex(text), ctx.lease.token),
                        )
                    cur.execute(
                        """UPDATE tool_executions SET status = 'succeeded', finished_at = now()
                           WHERE tool_execution_id = %s""",
                        (execution_id,),
                    )
                    add_event(cur, run_id, "task_completed", {"task_id": task_id, "passages": len(passages)})
        crash_if("after_evidence_commit")
        rows = ctx.conn.execute(
            "SELECT evidence_id FROM evidence WHERE run_id = %s ORDER BY evidence_id", (run_id,)
        ).fetchall()
        return {"evidence_ids": [r["evidence_id"] for r in rows]}

    def writer(state: RunGraphState) -> RunGraphState:
        crash_if("before_writer")
        transition(RunState.WRITING)
        # Run-scoped authorization: only evidence committed for this run may be cited.
        authorized = {
            r["evidence_id"]
            for r in ctx.conn.execute("SELECT evidence_id FROM evidence WHERE run_id = %s", (run_id,))
        }
        version = state.get("report_version", 0) + 1
        draft, _ = fakes.call_structured(
            fakes.writer_model(sorted(authorized), version, state["plan_version"]),
            WriterOutput,
            "Write the report from the evidence only.",
        )
        if errors := validate_citations(draft, authorized):
            raise CitationCheckFailed(f"{len(errors)} unresolved evidence references")
        with fenced(ctx.conn, ctx.lease) as cur:
            inserted = cur.execute(
                """INSERT INTO report_versions (run_id, version, digest, body) VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (run_id, version, artifact_digest(draft), Jsonb(draft.model_dump(mode="json"))),
            ).rowcount
            row = cur.execute(
                "SELECT digest FROM report_versions WHERE run_id = %s AND version = %s", (run_id, version)
            ).fetchone()
            if inserted:
                add_event(cur, run_id, "report_drafted", {"version": version})
        crash_if("after_report_commit")
        return {"report_version": version, "report_digest": row["digest"]}

    def reviewer(state: RunGraphState) -> RunGraphState:
        transition(RunState.REVIEWING)
        review_round = state.get("review_round", 0) + 1
        review = ReviewerOutput(report_version=state["report_version"], review_round=review_round, outcome="pass")
        next_state = route_after_review(review.outcome, review_round)
        with fenced(ctx.conn, ctx.lease) as cur:
            add_event(cur, run_id, "review_completed", {"round": review_round, "outcome": review.outcome})
        return {"review_round": review_round, "review_next": next_state.value}

    def await_report(state: RunGraphState) -> RunGraphState:
        resume = interrupt(
            {"kind": "report", "version": state["report_version"], "digest": state["report_digest"]}
        )
        decision = verified_decision(resume, "report", state["report_version"], state["report_digest"])
        return {"report_decision": decision}

    def finalize(state: RunGraphState) -> RunGraphState:
        approved = state["report_decision"] == "approve"
        transition(RunState.SUCCEEDED if approved else RunState.NEEDS_ATTENTION)
        return {}

    def needs_attention(state: RunGraphState) -> RunGraphState:
        transition(RunState.NEEDS_ATTENTION)
        return {}

    review_routes = {
        RunState.AWAITING_REPORT_APPROVAL.value: "await_report",
        RunState.WRITING.value: "writer",
        RunState.RESEARCHING.value: "research",
        RunState.NEEDS_ATTENTION.value: "needs_attention",
    }

    builder = StateGraph(RunGraphState)
    for name, fn in [
        ("planner", planner),
        ("await_plan", await_plan),
        ("research", research),
        ("writer", writer),
        ("reviewer", reviewer),
        ("await_report", await_report),
        ("finalize", finalize),
        ("needs_attention", needs_attention),
    ]:
        builder.add_node(name, fn)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "await_plan")
    builder.add_conditional_edges(
        "await_plan",
        lambda s: "research" if s["plan_decision"] == "approve" else "planner",
        ["research", "planner"],
    )
    builder.add_edge("research", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_conditional_edges("reviewer", lambda s: review_routes[s["review_next"]], list(review_routes.values()))
    builder.add_edge("await_report", "finalize")
    builder.add_edge("finalize", END)
    builder.add_edge("needs_attention", END)
    return builder.compile(checkpointer=checkpointer)
