"""The controlled research workflow as a LangGraph state graph (ADR 0006, 0007).

    planner → await_plan ─approve→ research → writer → reviewer ─pass→ await_report → finalize
                 └─reject→ planner          ↑         ├─revise──────┘(writer)
                                            └─────────┴─insufficient evidence (research)
    Exhausted review rounds, or no evidence at all → needs_attention.

Nodes may run more than once (crash recovery; LangGraph re-executes a node from its start
when an interrupt is resumed). Every side effect is idempotent: versions are derived from
checkpointed state, inserts use deterministic keys with ON CONFLICT DO NOTHING, and the
first committed result wins.
"""

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.agents.base import EvidenceView
from app.billing.meter import BudgetExhausted
from app.contracts import (
    Plan,
    PlanPolicyViolation,
    PlanTask,
    ResearcherOutput,
    ReviewerOutput,
    ReviewFinding,
    WriterOutput,
    artifact_digest,
    enforce_plan_policy,
    route_after_review,
    validate_citations,
)
from app.contracts.run_state import RunState
from app.db.models import (
    Approval,
    EvidencePassage,
    PlanVersion,
    ReportVersion,
    ReviewFindingRow,
    RunEvent,
    Source,
    TaskResult,
)
from app.observability.tracing import span
from app.policy.tools import allowed_tools, plan_policy_for
from app.services.events import append_event
from app.services.runs import latest_artifact
from app.tools.research import RunResearchTools, ToolLimitReached
from app.workflow.context import RunContext
from app.workflow.errors import StepFailed


class RunGraphState(TypedDict, total=False):
    plan_version: int
    plan_digest: str
    plan: dict[str, Any]
    plan_decision: str
    plan_feedback: str | None
    report_version: int
    report_digest: str
    review_round: int
    review_next: str
    review_findings: list[dict[str, Any]]
    supplementary_tasks: list[dict[str, Any]]
    report_decision: str
    attention_reason: str | None


def provenance(generation: dict[str, Any]) -> dict[str, Any]:
    """Event-safe summary of how an artifact was produced (no prompts or outputs)."""
    keys = ("provider", "model", "prompt_version", "attempts", "input_tokens", "output_tokens")
    return {k: generation[k] for k in keys if k in generation}


def load_evidence(ctx: RunContext) -> list[EvidenceView]:
    with ctx.sm() as session:
        rows = session.execute(
            select(EvidencePassage, Source.title, Source.url, Source.published_on)
            .join(
                Source,
                (Source.run_id == EvidencePassage.run_id) & (Source.source_id == EvidencePassage.source_id),
            )
            .where(EvidencePassage.run_id == ctx.run_id, Source.fetch_status == "fetched")
            .order_by(EvidencePassage.task_id, EvidencePassage.evidence_id)
        ).all()
    return [
        EvidenceView(e.evidence_id, e.source_id, e.task_id, title, url, published, e.text)
        for e, title, url, published in rows
    ]


def build_graph(
    ctx: RunContext, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[Any, Any, Any, Any]:
    run_id = ctx.run_id
    brief = ctx.brief

    def verified_approval(resume: Any, kind: str) -> Approval:
        """Defence in depth: the decision service already bound the approval to the latest
        version and digest; re-check against immutable stored artifacts before acting."""
        with ctx.sm() as session:
            approval = session.get(Approval, resume["approval_id"]) if isinstance(resume, dict) else None
            latest = latest_artifact(session, run_id, kind)
        if (
            approval is None
            or approval.run_id != run_id
            or approval.artifact_kind != kind
            or latest is None
            or approval.artifact_version != latest.version
            or approval.artifact_digest != latest.digest
        ):
            raise StepFailed(f"await_{kind}", "approval does not bind to the current artifact")
        return approval

    def planner(state: RunGraphState) -> RunGraphState:
        ctx.transition(RunState.PLANNING)
        version = state.get("plan_version", 0) + 1
        call = ctx.agents.planner.plan(brief, version=version, feedback=state.get("plan_feedback"))
        # The server assigns versions and limits; the model cannot widen the tool allowlist.
        plan = Plan.model_validate({**call.output.model_dump(mode="json"), "plan_version": version})
        try:
            enforce_plan_policy(plan, plan_policy_for(brief))
        except PlanPolicyViolation as exc:
            raise StepFailed("planner", f"plan violates policy: {exc}") from exc
        with ctx.fenced() as session:
            inserted = session.execute(
                insert(PlanVersion)
                .values(
                    run_id=run_id,
                    version=version,
                    digest=artifact_digest(plan),
                    body=plan.model_dump(mode="json"),
                    author="agent",
                    generation=call.generation,
                )
                .on_conflict_do_nothing()
                .returning(PlanVersion.version)
            ).first()
            stored = session.get(PlanVersion, (run_id, version))
            assert stored is not None
            if inserted:
                append_event(
                    session,
                    run_id,
                    ctx.workspace_id,
                    "plan_proposed",
                    {"version": version, "tasks": len(plan.tasks), **provenance(call.generation)},
                )
        ctx.crash_if("after_plan_commit")
        return {"plan_version": version, "plan_digest": stored.digest, "plan": stored.body}

    def await_plan(state: RunGraphState) -> RunGraphState:
        resume = interrupt({"kind": "plan", "version": state["plan_version"], "digest": state["plan_digest"]})
        approval = verified_approval(resume, "plan")
        with ctx.sm() as session:
            stored = session.get(PlanVersion, (run_id, approval.artifact_version))
            assert stored is not None
        return {
            "plan_decision": approval.decision,
            "plan_version": stored.version,
            "plan_digest": stored.digest,
            "plan": stored.body,
            "plan_feedback": approval.comment,
        }

    def research(state: RunGraphState) -> RunGraphState:
        ctx.transition(RunState.RESEARCHING)
        plan = Plan.model_validate(state["plan"])
        supplementary = [PlanTask.model_validate(t) for t in state.get("supplementary_tasks") or []]
        tasks_by_id = {t.task_id: t for t in (supplementary or plan.tasks)}
        levels = [[t.task_id for t in supplementary]] if supplementary else plan.execution_order()
        run_levels(ctx, [[tasks_by_id[t] for t in level] for level in levels])
        ctx.crash_if("after_research")
        with ctx.sm() as session:
            evidence_count = session.scalar(
                select(func.count()).select_from(EvidencePassage).where(EvidencePassage.run_id == run_id)
            )
        if not evidence_count:
            return {
                "supplementary_tasks": [],
                "attention_reason": "No evidence could be collected for any task",
            }
        return {"supplementary_tasks": [], "attention_reason": None}

    def writer(state: RunGraphState) -> RunGraphState:
        ctx.crash_if("before_writer")
        ctx.transition(RunState.WRITING)
        version = state.get("report_version", 0) + 1
        plan = Plan.model_validate(state["plan"])
        evidence = load_evidence(ctx)
        findings = [ReviewFinding.model_validate(f) for f in state.get("review_findings") or []]
        with ctx.sm() as session:
            existing = session.get(ReportVersion, (run_id, version))
        if existing is not None:
            # Re-executed after a crash: the committed version wins; no second (paid) draft.
            return {"report_version": version, "report_digest": existing.digest}
        call = ctx.agents.writer.write(brief, plan, evidence, report_version=version, findings=findings)
        draft = WriterOutput.model_validate(
            {
                **call.output.model_dump(mode="json"),
                "report_version": version,
                "plan_version": plan.plan_version,
            }
        )
        if errors := validate_citations(draft, {e.evidence_id for e in evidence}):
            raise StepFailed("writer", f"{len(errors)} citation(s) do not resolve to run evidence")
        with ctx.fenced() as session:
            inserted = session.execute(
                insert(ReportVersion)
                .values(
                    run_id=run_id,
                    version=version,
                    plan_version=plan.plan_version,
                    digest=artifact_digest(draft),
                    body=draft.model_dump(mode="json"),
                    generation=call.generation,
                )
                .on_conflict_do_nothing()
                .returning(ReportVersion.version)
            ).first()
            stored = session.get(ReportVersion, (run_id, version))
            assert stored is not None
            if inserted:
                claims = [c for s in draft.sections for c in s.claims]
                append_event(
                    session,
                    run_id,
                    ctx.workspace_id,
                    "report_drafted",
                    {
                        "version": version,
                        "sections": len(draft.sections),
                        "claims": len(claims),
                        "citations": sum(len(c.evidence_ids) for c in claims),
                        **provenance(call.generation),
                    },
                )
        ctx.crash_if("after_report_commit")
        return {"report_version": version, "report_digest": stored.digest}

    def reviewer(state: RunGraphState) -> RunGraphState:
        ctx.transition(RunState.REVIEWING)
        review_round = state.get("review_round", 0) + 1
        plan = Plan.model_validate(state["plan"])
        with ctx.sm() as session:
            stored = session.get(ReportVersion, (run_id, state["report_version"]))
            assert stored is not None
        draft = WriterOutput.model_validate(stored.body)
        committed = committed_review(ctx, draft.report_version)
        if committed is not None:
            # Re-executed after a crash: the first committed review wins (no second call,
            # which a model could answer differently).
            review = committed
        else:
            call = ctx.agents.reviewer.review(
                brief, plan, draft, load_evidence(ctx), review_round=review_round
            )
            review = ReviewerOutput.model_validate(
                {
                    **call.output.model_dump(mode="json"),
                    "report_version": draft.report_version,
                    "review_round": review_round,
                }
            )
        next_state = route_after_review(review.outcome, review_round)
        if committed is None:
            persist_review(ctx, review, next_state, call.generation)
        ctx.crash_if("after_review_commit")
        supplementary: list[dict[str, Any]] = []
        if next_state == RunState.RESEARCHING:
            supplementary = [
                PlanTask(
                    task_id=f"r{review_round}-{i}",
                    question=f.requested_action,
                    tools=sorted(allowed_tools(brief)),
                    expected_evidence="Evidence requested by review",
                    section_ids=[plan.outline[0].section_id],
                ).model_dump(mode="json")
                for i, f in enumerate(review.findings_by_severity()[: brief.limits.max_tasks], 1)
            ]
        attention = None
        if next_state == RunState.NEEDS_ATTENTION:
            attention = f"Review round {review_round} ended '{review.outcome}' with unresolved findings"
        return {
            "review_round": review_round,
            "review_next": next_state.value,
            "review_findings": [f.model_dump(mode="json") for f in review.findings_by_severity()],
            "supplementary_tasks": supplementary,
            "attention_reason": attention,
        }

    def await_report(state: RunGraphState) -> RunGraphState:
        resume = interrupt(
            {"kind": "report", "version": state["report_version"], "digest": state["report_digest"]}
        )
        approval = verified_approval(resume, "report")
        return {"report_decision": approval.decision}

    def finalize(state: RunGraphState) -> RunGraphState:
        ctx.crash_if("before_finalize")
        if state["report_decision"] == "approve":
            ctx.transition(RunState.SUCCEEDED)
        else:
            ctx.transition(
                RunState.NEEDS_ATTENTION, "Report rejected by reviewer; it is not exportable as approved"
            )
        return {}

    def needs_attention(state: RunGraphState) -> RunGraphState:
        ctx.transition(RunState.NEEDS_ATTENTION, state.get("attention_reason") or "Needs attention")
        return {}

    review_routes = {
        RunState.AWAITING_REPORT_APPROVAL.value: "await_report",
        RunState.WRITING.value: "writer",
        RunState.RESEARCHING.value: "research",
        RunState.NEEDS_ATTENTION.value: "needs_attention",
    }

    builder: StateGraph[Any, Any, Any, Any] = StateGraph(RunGraphState)
    for name, node in (
        ("planner", planner),
        ("await_plan", await_plan),
        ("research", research),
        ("writer", writer),
        ("reviewer", reviewer),
        ("await_report", await_report),
        ("finalize", finalize),
        ("needs_attention", needs_attention),
    ):
        builder.add_node(name, _traced(name, node, ctx))
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "await_plan")
    builder.add_conditional_edges(
        "await_plan",
        lambda s: "research" if s["plan_decision"] == "approve" else "planner",
        ["research", "planner"],
    )
    builder.add_conditional_edges(
        "research",
        lambda s: "needs_attention" if s.get("attention_reason") else "writer",
        ["writer", "needs_attention"],
    )
    builder.add_edge("writer", "reviewer")
    builder.add_conditional_edges(
        "reviewer", lambda s: review_routes[s["review_next"]], list(review_routes.values())
    )
    builder.add_edge("await_report", "finalize")
    builder.add_edge("finalize", END)
    builder.add_edge("needs_attention", END)
    return builder.compile(checkpointer=checkpointer)


def committed_review(ctx: RunContext, report_version: int) -> ReviewerOutput | None:
    """The review already committed for this report version, if any (crash recovery)."""
    with ctx.sm() as session:
        event = session.scalars(
            select(RunEvent)
            .where(
                RunEvent.run_id == ctx.run_id,
                RunEvent.event_type == "review_completed",
                RunEvent.payload["report_version"].as_integer() == report_version,
            )
            .order_by(RunEvent.id)
            .limit(1)
        ).first()
        if event is None:
            return None
        rows = session.scalars(
            select(ReviewFindingRow).where(
                ReviewFindingRow.run_id == ctx.run_id, ReviewFindingRow.report_version == report_version
            )
        ).all()
    return ReviewerOutput(
        report_version=report_version,
        review_round=int(event.payload["round"]),
        outcome=event.payload["outcome"],
        findings=[
            ReviewFinding(
                finding_id=r.finding_id,
                severity=r.severity,
                category=r.category,
                claim_ids=r.claim_ids,
                evidence_ids=r.evidence_ids,
                requested_action=r.requested_action,
            )
            for r in rows
        ],
    )


def persist_review(
    ctx: RunContext, review: ReviewerOutput, next_state: RunState, generation: dict[str, Any]
) -> None:
    """Findings and the review event commit together, fenced; the event marks the review as
    committed, so a re-executed node reuses it instead of reviewing again."""
    severities = {s: sum(f.severity == s for f in review.findings) for s in ("blocker", "major", "minor")}
    with ctx.fenced() as session:
        if review.findings:
            session.execute(
                insert(ReviewFindingRow)
                .values(
                    [
                        {
                            "run_id": ctx.run_id,
                            "report_version": review.report_version,
                            "finding_id": f.finding_id,
                            "review_round": review.review_round,
                            "severity": f.severity,
                            "category": f.category,
                            "source": "deterministic" if f.finding_id.startswith("d-") else "model",
                            "claim_ids": list(f.claim_ids),
                            "evidence_ids": list(f.evidence_ids),
                            "requested_action": f.requested_action[:500],
                        }
                        for f in review.findings
                    ]
                )
                .on_conflict_do_nothing()
            )
        append_event(
            session,
            ctx.run_id,
            ctx.workspace_id,
            "review_completed",
            {
                "round": review.review_round,
                "report_version": review.report_version,
                "outcome": review.outcome,
                "findings": severities,
                "next": next_state.value,
                **provenance(generation),
            },
        )


def _traced(name: str, node: Any, ctx: RunContext) -> Any:
    def run(state: RunGraphState) -> RunGraphState:
        with span(f"step.{name}", expected=(GraphBubbleUp,), step=name, run_id=ctx.run_id):
            result: RunGraphState = node(state)
            return result

    return run


def run_levels(ctx: RunContext, levels: list[list[PlanTask]]) -> None:
    """Run tasks level by level (dependencies first), up to `max_parallel_tasks` at once.
    Exhausting the budget or tool-call limit stops scheduling; unfinished tasks are recorded
    as stopped rather than silently dropped. Other errors propagate to the worker, which
    retries transient ones (committed tasks are then skipped)."""
    stop = threading.Event()
    for level in levels:
        workers = max(1, min(len(level), ctx.brief.limits.max_parallel_tasks))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"research-{ctx.run_id}") as pool:
            futures = [
                pool.submit(contextvars.copy_context().run, run_research_task, ctx, task, stop)
                for task in level
            ]
            errors = [f.exception() for f in futures if f.exception() is not None]
        if errors:
            raise errors[0]  # type: ignore[misc]


def _record_task(
    ctx: RunContext, task: PlanTask, output: ResearcherOutput, status: str, event: dict[str, Any]
) -> None:
    with ctx.fenced() as session:
        inserted = session.execute(
            insert(TaskResult)
            .values(
                run_id=ctx.run_id,
                task_id=task.task_id,
                status=status,
                output=output.model_dump(mode="json"),
                fencing_token=ctx.lease.token,
            )
            .on_conflict_do_nothing()
            .returning(TaskResult.task_id)
        ).first()
        if inserted:
            append_event(
                session,
                ctx.run_id,
                ctx.workspace_id,
                "task_completed",
                {"task_id": task.task_id, "status": status, **event},
            )
    if inserted:
        ctx.crash_if("after_task_commit")


def run_research_task(ctx: RunContext, task: PlanTask, stop: threading.Event | None = None) -> None:
    with span("research.task", run_id=ctx.run_id, task_id=task.task_id):
        _run_research_task(ctx, task, stop)


def _run_research_task(ctx: RunContext, task: PlanTask, stop: threading.Event | None = None) -> None:
    """Run one task unless its result is already committed (at-least-once, idempotent)."""
    with ctx.sm() as session:
        if session.get(TaskResult, (ctx.run_id, task.task_id)) is not None:
            return
    if stop is not None and stop.is_set():
        _record_task(
            ctx,
            task,
            ResearcherOutput(task_id=task.task_id, unresolved_questions=[task.question]),
            "failed",
            {"evidence": 0, "unresolved": 1, "stopped": "not started: run limits reached"},
        )
        return
    try:
        call = ctx.agents.researcher.research(ctx.brief, task, RunResearchTools(ctx, task.task_id))
    except (BudgetExhausted, ToolLimitReached) as exc:
        if stop is not None:
            stop.set()
        _record_task(
            ctx,
            task,
            ResearcherOutput(task_id=task.task_id, unresolved_questions=[task.question]),
            "failed",
            {"evidence": 0, "unresolved": 1, "stopped": str(exc)[:200]},
        )
        return
    output = call.output
    if output.task_id != task.task_id:
        raise StepFailed(
            "research", f"researcher answered task {output.task_id!r}, expected {task.task_id!r}"
        )
    with ctx.sm() as session:
        known = set(
            session.scalars(select(EvidencePassage.evidence_id).where(EvidencePassage.run_id == ctx.run_id))
        )
    if unknown := sorted(set(output.evidence_ids) - known):
        raise StepFailed("research", f"researcher cited {len(unknown)} evidence id(s) it did not collect")
    _record_task(
        ctx,
        task,
        output,
        "succeeded" if output.evidence_ids else "no_evidence",
        {
            "evidence": len(output.evidence_ids),
            "unresolved": len(output.unresolved_questions),
            "conflicts": len(output.conflicts),
            **provenance(call.generation),
        },
    )
