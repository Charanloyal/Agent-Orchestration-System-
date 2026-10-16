"""Evaluation harness: runs cases x systems through the real workflow and records results.

Each run gets its own workspace (uploads never leak between cases), its own offline corpus
folder, and the case's fault fixtures. Plan and report approvals are answered by a *simulated
human* that always approves; this is recorded in the results and is a stated limitation
(real reviewer effort is measured separately, in the blind scoring kit).
"""

import json
import platform
import secrets
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Float, cast, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import EvidenceView
from app.agents.review_checks import deterministic_findings
from app.auth.deps import Principal
from app.billing.meter import spend_for
from app.config import Settings
from app.contracts import WriterOutput, validate_citations
from app.contracts.run_state import TERMINAL_STATES
from app.db.models import (
    Approval,
    BudgetReservation,
    EvidencePassage,
    Membership,
    ReportVersion,
    ReviewFindingRow,
    Role,
    Run,
    RunEvent,
    RunJob,
    Source,
    ToolExecution,
    User,
    Workspace,
)
from app.db.session import get_sessionmaker
from app.providers.breaker import reset_breakers
from app.providers.corpus import CorpusSearch
from app.providers.llm import LlmProvider
from app.providers.search import SearchProvider
from app.services.exports import export_report
from app.services.runs import create_run, decide, latest_artifact
from app.services.uploads import ingest_upload
from app.storage import get_object_store
from app.workers.runner import process_one
from evaluation.cases import REPO_ROOT, CaseFixture, corpus_digest
from evaluation.metrics import observed_outcome, outcome_matches, summarize
from evaluation.systems import (
    SYSTEMS,
    FailingLlm,
    FlakySearch,
    Mode,
    NoNetworkFetcher,
    SystemId,
    suite_factory,
)

MAX_PASSES = 25
FAKE_LABEL = "FAKE-AGENT HARNESS VALIDATION: not a quality result"
LIVE_LABEL = "LIVE-PROVIDER RUN: automated metrics only until blind human scoring is merged"


@dataclass(frozen=True)
class Actors:
    analyst: Principal
    reviewer: Principal


@dataclass
class RunLog:
    passes: int = 0
    retries: int = 0
    skipped_backoff_seconds: float = 0.0
    active_seconds: float = 0.0
    seconds_to_report: float | None = None
    reached_report: bool = False
    simulated_decisions: list[str] = field(default_factory=list)


def seed_actors(sm: sessionmaker[Session], tag: str) -> Actors:
    """Bot users for the simulated human. Fresh per harness invocation."""
    with sm() as db:
        users = []
        for name in ("Evaluation analyst", "Evaluation reviewer"):
            user = User(
                oidc_issuer="urn:aos:evaluation",
                oidc_subject=f"{name.split()[-1]}-{tag}",
                email=None,
                display_name=f"{name} (simulated)",
            )
            db.add(user)
            users.append(user)
        db.commit()
        principals = [Principal(u.id, uuid.uuid4(), "evaluation", None, u.display_name) for u in users]
    return Actors(*principals)


def _new_workspace(db: Session, actors: Actors, name: str) -> uuid.UUID:
    workspace = Workspace(name=name[:200])
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=actors.analyst.user_id, role=Role.ANALYST))
    db.add(Membership(workspace_id=workspace.id, user_id=actors.reviewer.user_id, role=Role.REVIEWER))
    db.commit()
    return workspace.id


def _approve(db: Session, actors: Actors, run_id: uuid.UUID, kind: str) -> None:
    artifact = latest_artifact(db, run_id, kind)
    assert artifact is not None
    principal = actors.analyst if kind == "plan" else actors.reviewer
    decide(
        db,
        principal,
        run_id,
        kind=kind,
        version=artifact.version,
        digest=artifact.digest,
        decision="approve",
        comment="Simulated human approval (evaluation harness)",
    )


def _skip_backoff(db: Session, run_id: uuid.UUID) -> float:
    """Transient-error backoff is real in production; the harness skips the wait (recorded)."""
    job = db.get(RunJob, run_id)
    assert job is not None
    waited = max(0.0, (job.available_at - datetime.now(UTC)).total_seconds())
    db.execute(update(RunJob).where(RunJob.run_id == run_id).values(available_at=func.now()))
    db.commit()
    return waited


def drive(
    settings: Settings,
    sm: sessionmaker[Session],
    actors: Actors,
    run_id: uuid.UUID,
    *,
    search: SearchProvider,
    fetcher: NoNetworkFetcher,
    llm: LlmProvider | None,
    system: SystemId,
    mode: Mode,
    model_fault: str | None,
) -> RunLog:
    log = RunLog()
    factory = suite_factory(system, mode, model_fault)
    for _ in range(MAX_PASSES):
        started = time.perf_counter()
        outcome = process_one(
            settings, run_id=run_id, search=search, fetcher=fetcher, llm=llm, agent_factory=factory
        )
        log.active_seconds += time.perf_counter() - started
        log.passes += 1
        with sm() as db:
            if outcome == "waiting_plan":
                _approve(db, actors, run_id, "plan")
                log.simulated_decisions.append("plan:approve")
                continue
            if outcome == "waiting_report":
                log.reached_report = True
                log.seconds_to_report = log.active_seconds
                _approve(db, actors, run_id, "report")
                log.simulated_decisions.append("report:approve")
                continue
            if outcome == "retry":
                log.retries += 1
                log.skipped_backoff_seconds += _skip_backoff(db, run_id)
                continue
            run = db.get(Run, run_id)
            assert run is not None
            if run.state in TERMINAL_STATES:
                break
    return log


def _evidence(db: Session, run_id: uuid.UUID) -> tuple[dict[str, EvidenceView], dict[str, str | None]]:
    rows = db.execute(
        select(EvidencePassage, Source.title, Source.url, Source.published_on)
        .join(
            Source,
            (Source.run_id == EvidencePassage.run_id) & (Source.source_id == EvidencePassage.source_id),
        )
        .where(EvidencePassage.run_id == run_id, Source.fetch_status == "fetched")
    ).all()
    views = {
        e.evidence_id: EvidenceView(e.evidence_id, e.source_id, e.task_id, title, url, published, e.text)
        for e, title, url, published in rows
    }
    return views, {e.evidence_id: published for e, _, _, published in rows}


def collect(
    db: Session,
    fixture: CaseFixture,
    run_id: uuid.UUID,
    log: RunLog,
    fetcher: NoNetworkFetcher,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (metrics record, artifact with report body and cited passages for scoring)."""
    run = db.get(Run, run_id)
    assert run is not None
    versions = db.scalars(
        select(ReportVersion).where(ReportVersion.run_id == run_id).order_by(ReportVersion.version)
    ).all()
    evidence, published = _evidence(db, run_id)
    final = WriterOutput.model_validate(versions[-1].body) if versions else None
    claims = [c for s in final.sections for c in s.claims] if final else []
    citation_errors = validate_citations(final, set(evidence)) if final else []
    findings = deterministic_findings(final, evidence) if final else []
    flagged = {cid for f in findings for cid in f.claim_ids}
    facts = [c for c in claims if c.kind == "fact"]
    states = [
        e.payload.get("to")
        for e in db.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.event_type == "state_changed")
            .order_by(RunEvent.id)
        )
    ]
    review_events = db.scalars(
        select(RunEvent.payload).where(RunEvent.run_id == run_id, RunEvent.event_type == "review_completed")
    ).all()
    # The ablated reviewer still emits the event (provider "none"); only real checks count.
    review_rounds = sum(1 for p in review_events if p.get("provider") != "none")
    finding_rows = db.execute(
        select(ReviewFindingRow.severity, ReviewFindingRow.source, func.count())
        .where(ReviewFindingRow.run_id == run_id)
        .group_by(ReviewFindingRow.severity, ReviewFindingRow.source)
    ).all()
    tools = Counter(
        dict(
            db.execute(
                select(ToolExecution.tool, func.count())
                .where(ToolExecution.run_id == run_id)
                .group_by(ToolExecution.tool)
            ).all()
        )
    )
    tool_status = Counter(
        dict(
            db.execute(
                select(ToolExecution.status, func.count())
                .where(ToolExecution.run_id == run_id)
                .group_by(ToolExecution.status)
            ).all()
        )
    )
    spend = spend_for(db, run_id, Decimal(str(fixture.case.brief.budget.max_estimated_cost)))
    tokens_in, tokens_out = db.execute(
        select(
            func.coalesce(func.sum(cast(BudgetReservation.usage["input_tokens"].astext, Float)), 0),
            func.coalesce(func.sum(cast(BudgetReservation.usage["output_tokens"].astext, Float)), 0),
        ).where(BudgetReservation.run_id == run_id)
    ).one()
    approvals = db.scalars(select(Approval.decided_by).where(Approval.run_id == run_id)).all()

    expected = fixture.case.expected.outcome
    observed = observed_outcome(run.state, log.reached_report, bool(versions))
    checks: dict[str, bool] = {
        "no_network_fetch_attempted": not fetcher.attempts and tools.get("fetch_url", 0) == 0,
        "human_gate_not_bypassed": run.state != "SUCCEEDED"
        or ("AWAITING_REPORT_APPROVAL" in states and len(approvals) >= 2),
    }
    if final is not None:
        checks["no_unsupported_figures_in_final_report"] = not any(
            f.finding_id.startswith("d-num-") for f in findings
        )
    cutoff = fixture.case.brief.source_policy.date_cutoff
    if cutoff is not None:
        cited = {e for c in claims for e in c.evidence_ids}
        checks["no_source_older_than_cutoff_cited"] = not any(
            published.get(e) and date.fromisoformat(str(published[e])[:10]) < cutoff for e in cited
        )
    if expected == "failed_safely":
        checks["no_report_after_model_failure"] = not versions

    record = {
        "case_id": fixture.case_id,
        "split": fixture.case.split,
        "category": fixture.case.category,
        "expected_outcome": expected,
        "observed_outcome": observed,
        "outcome_matches": outcome_matches(expected, observed),
        "final_state": run.state,
        "outcome_reason": run.outcome_reason,
        "operational_failure": run.state == "FAILED" and expected != "failed_safely",
        "states": states,
        "passes": log.passes,
        "transient_retries": log.retries,
        "skipped_backoff_seconds": round(log.skipped_backoff_seconds, 2),
        "simulated_decisions": log.simulated_decisions,
        "latency_seconds": round(
            log.seconds_to_report if log.seconds_to_report is not None else log.active_seconds, 3
        ),
        "latency_basis": "to_reviewable_draft" if log.seconds_to_report is not None else "to_terminal_state",
        "report": {
            "versions": len(versions),
            "claims": len(claims),
            "claims_by_kind": dict(Counter(c.kind for c in claims)),
            "citations": sum(len(c.evidence_ids) for c in claims),
            "valid_citations": sum(len(c.evidence_ids) for c in claims) - len(citation_errors),
            "fact_claims": len(facts),
            "fact_claims_passing_checks": sum(c.claim_id not in flagged for c in facts),
        },
        "review": {
            "rounds": review_rounds,
            "pass_through_rounds": len(review_events) - review_rounds,
            "findings": {f"{sev}/{src}": n for sev, src, n in finding_rows},
        },
        "tools": {
            "by_tool": dict(tools),
            "by_status": dict(tool_status),
            "refused_fetches": len(fetcher.attempts),
        },
        "evidence_passages": len(evidence),
        "cost": {
            "committed": str(spend.committed),
            "reconciled": str(spend.reconciled),
            "uncertain": str(spend.uncertain),
            "llm_input_tokens": int(tokens_in),
            "llm_output_tokens": int(tokens_out),
        },
        "must_not_checks": checks,
    }
    artifact = {
        "case_id": fixture.case_id,
        "brief": fixture.case.brief.model_dump(mode="json"),
        "must_cover": fixture.case.expected.must_cover,
        "must_not": fixture.case.expected.must_not,
        "report": final.model_dump(mode="json") if final else None,
        "cited_passages": {
            e: {"title": evidence[e].title, "url": evidence[e].url, "text": evidence[e].text}
            for c in claims
            for e in c.evidence_ids
            if e in evidence
        },
    }
    return record, artifact


def run_case(
    settings: Settings,
    fixture: CaseFixture,
    system: SystemId,
    repeat: int,
    *,
    mode: Mode,
    actors: Actors,
    live_llm: LlmProvider | None,
    out_dir: Path,
) -> dict[str, Any]:
    sm = get_sessionmaker()
    reset_breakers()
    key = f"{fixture.case_id}__{system}__r{repeat}"
    with sm() as db:
        workspace_id = _new_workspace(db, actors, f"eval {key}")
        for upload in fixture.uploads:
            ingest_upload(
                db,
                get_object_store(),
                actors.analyst,
                workspace_id,
                filename=upload.filename,
                data=upload.text.encode(),
                max_bytes=settings.upload_max_bytes,
            )
        created = create_run(
            db,
            actors.analyst,
            workspace_id=workspace_id,
            brief=fixture.case.brief,
            idempotency_key=f"eval-{uuid.uuid4().hex}",
            settings=settings,
        )
        run_id = created.run.id

    search: SearchProvider = CorpusSearch(fixture.docs_dir)
    if fixture.search_fault:
        search = FlakySearch(search, fixture.search_fault.status, fixture.search_fault.times)
    fetcher = NoNetworkFetcher()
    llm: LlmProvider | None = None
    if mode == "llm":
        llm = FailingLlm(fixture.model_fault) if fixture.model_fault else live_llm
    log = drive(
        settings,
        sm,
        actors,
        run_id,
        search=search,
        fetcher=fetcher,
        llm=llm,
        system=system,
        mode=mode,
        model_fault=fixture.model_fault,
    )
    with sm() as db:
        record, artifact = collect(db, fixture, run_id, log, fetcher)
        if record["report"]["versions"]:
            run = db.get(Run, run_id)
            assert run is not None
            exported = export_report(
                db,
                get_object_store(),
                run=run,
                version=record["report"]["versions"],
                user_id=actors.reviewer.user_id,
            )
            (out_dir / "reports").mkdir(parents=True, exist_ok=True)
            (out_dir / "reports" / f"{key}.md").write_bytes(exported.content)
    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (out_dir / "artifacts" / f"{key}.json").write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False), "utf-8"
    )
    record.update({"key": key, "system": system, "repeat": repeat, "run_id": str(run_id)})
    return record


def git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            ["git", *args],  # noqa: S607 - git from PATH, as for any developer tool
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


@dataclass(frozen=True)
class EvaluationConfig:
    split: str
    systems: list[SystemId]
    case_ids: list[str]
    repeats: int
    repeat_case_ids: list[str]
    mode: Mode
    live_budget_usd: float | None = None


def run_evaluation(
    settings: Settings,
    fixtures: list[CaseFixture],
    config: EvaluationConfig,
    results_root: Path,
    *,
    live_llm: LlmProvider | None = None,
    label: str = "dev",
) -> Path:
    started = datetime.now(UTC)
    run_tag = f"{started:%Y-%m-%d}-{label}-{config.mode}-{secrets.token_hex(3)}"
    out_dir = results_root / run_tag
    out_dir.mkdir(parents=True, exist_ok=False)
    actors = seed_actors(get_sessionmaker(), run_tag)
    records: list[dict[str, Any]] = []
    spent = Decimal(0)
    stopped_early = None
    with (out_dir / "runs.jsonl").open("w", encoding="utf-8") as runs_file:
        for fixture in fixtures:
            repeats = config.repeats if fixture.case_id in config.repeat_case_ids else 1
            for system in config.systems:
                for repeat in range(1, repeats + 1):
                    record = run_case(
                        settings,
                        fixture,
                        system,
                        repeat,
                        mode=config.mode,
                        actors=actors,
                        live_llm=live_llm,
                        out_dir=out_dir,
                    )
                    records.append(record)
                    runs_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    runs_file.flush()
                    spent += Decimal(record["cost"]["committed"])
                    if config.live_budget_usd is not None and spent >= Decimal(str(config.live_budget_usd)):
                        stopped_early = (
                            f"live budget of ${config.live_budget_usd} reached after {len(records)} runs"
                        )
                        break
                if stopped_early:
                    break
            if stopped_early:
                break

    summary = summarize(records)
    finished = datetime.now(UTC)
    settings_view = {
        "agent_mode": config.mode,
        "llm_model": settings.llm_model if config.mode == "llm" else None,
        "llm_base_url": settings.llm_base_url if config.mode == "llm" else None,
        "search_provider": "corpus (eval/corpus/v1, per-case folders)",
        "price_schedule_id": settings.price_schedule_id,
        "job_max_attempts": settings.job_max_attempts,
    }
    meta = {
        "run_tag": run_tag,
        "label": FAKE_LABEL if config.mode == "fake" else LIVE_LABEL,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "git": git_state(),
        "python": platform.python_version(),
        "split": config.split,
        "systems": {s: SYSTEMS[s] for s in config.systems},
        "case_ids": config.case_ids,
        "repeats": config.repeats,
        "repeat_case_ids": config.repeat_case_ids,
        "corpus_manifest_sha256": corpus_digest(),
        "settings": settings_view,
        "simulated_human": "Plan and report approvals are given automatically by the harness.",
        "live_budget_usd": config.live_budget_usd,
        "live_spend_usd_estimated": str(spent),
        "stopped_early": stopped_early,
    }
    (out_dir / "config.json").write_text(json.dumps(meta, indent=2), "utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    (out_dir / "summary.md").write_text(render_summary(meta, summary, records), "utf-8")
    return out_dir


def _pct(p: dict[str, Any]) -> str:
    if not p["total"]:
        return "n/a (0)"
    ci = p["ci95"]
    return f"{p['rate']:.0%} ({p['successes']}/{p['total']}; 95% CI {ci[0]:.0%}-{ci[1]:.0%})"


def render_summary(meta: dict[str, Any], summary: dict[str, Any], records: list[dict[str, Any]]) -> str:
    git = meta["git"]
    lines = [
        f"# Evaluation results: {meta['run_tag']}",
        "",
        f"> **{meta['label']}**",
        "",
        f"- Split: `{meta['split']}`; cases: {len(meta['case_ids'])}; runs: {len(records)}",
        f"- Commit: `{git['commit'][:12]}`{' (uncommitted changes)' if git['dirty'] else ''}",
        f"- Agent mode: `{meta['settings']['agent_mode']}`; "
        f"corpus manifest `{meta['corpus_manifest_sha256'][:12]}`",
        f"- {meta['simulated_human']}",
        "- Automated metrics only. Evidence support, coverage and uncertainty handling require the",
        "  blind human scoring kit (`python -m evaluation.blind`).",
        "",
    ]
    for system, groups in summary.items():
        lines += [f"## System {system}: {meta['systems'].get(system, '')}", ""]
        lines += [
            "| Metric | All | Answerable | Unanswerable / adversarial |",
            "| --- | --- | --- | --- |",
        ]
        rows = [
            ("Outcome matches expected", "outcome_matches_expected"),
            ("Operational failures", "operational_failures"),
            ("Citation validity", "citation_validity"),
            ("Fact claims passing automatic checks (proxy)", "fact_claims_passing_automatic_checks_PROXY"),
        ]
        for title, key in rows:
            lines.append(
                f"| {title} | {_pct(groups['all'][key])} | {_pct(groups['answerable'][key])} "
                f"| {_pct(groups['unanswerable_or_adversarial'][key])} |"
            )
        all_ = groups["all"]
        lines += [
            f"| Mean review rounds | {all_['review_rounds_mean']:.2f} | | |"
            if all_["review_rounds_mean"] is not None
            else "| Mean review rounds | n/a | | |",
            f"| Revisions | {all_['revisions_total']} | | |",
            f"| Latency median / p95 (s, excl. human + skipped backoff) | "
            f"{all_['latency_seconds']['median']} / {all_['latency_seconds']['p95']} | | |",
            f"| Estimated cost total (USD) | {all_['cost_usd']['total']} | | |",
            "",
            "Mechanical `must_not` checks:",
            "",
        ]
        for name, p in all_["mechanical_must_not_checks"].items():
            lines.append(f"- `{name}`: {_pct(p)}")
        lines.append("")
    lines += [
        "## Per-run outcomes",
        "",
        "| Run | Expected | Observed | Final state | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in records:
        reason = (r["outcome_reason"] or "").replace("|", "/")[:90]
        mark = "" if r["outcome_matches"] else " ✗"
        lines.append(
            f"| `{r['key']}` | {r['expected_outcome']} | {r['observed_outcome']}{mark} "
            f"| {r['final_state']} | {reason} |"
        )
    lines.append("")
    return "\n".join(lines)
