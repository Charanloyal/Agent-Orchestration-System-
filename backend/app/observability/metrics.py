"""Prometheus text-format metrics (ADR 0016) without an extra dependency.

Two kinds:
- HTTP request counters and latency histograms, kept in this API process;
- workflow gauges computed from PostgreSQL at scrape time. Workers are separate processes,
  so the database is the one place that sees every run, job, call, and reservation.
"""

import threading
from bisect import bisect_left
from collections import defaultdict

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import BudgetReservation, ReviewFindingRow, Run, RunJob, ToolExecution

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class HttpMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self.buckets: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self.sums: dict[tuple[str, str], float] = defaultdict(float)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(method, route, str(status))] += 1
            self.buckets[(method, route)][bisect_left(BUCKETS, seconds)] += 1
            self.sums[(method, route)] += seconds

    def render(self) -> list[str]:
        with self._lock:
            lines = [
                "# HELP aos_http_requests_total HTTP requests by route template and status.",
                "# TYPE aos_http_requests_total counter",
            ]
            for (method, route, status), n in sorted(self.requests.items()):
                labels = f'method="{method}",route="{_esc(route)}",status="{status}"'
                lines.append(f"aos_http_requests_total{{{labels}}} {n}")
            lines += [
                "# HELP aos_http_request_duration_seconds HTTP request latency.",
                "# TYPE aos_http_request_duration_seconds histogram",
            ]
            for (method, route), counts in sorted(self.buckets.items()):
                labels = f'method="{method}",route="{_esc(route)}"'
                cumulative = 0
                for bound, count in zip((*BUCKETS, float("inf")), counts, strict=True):
                    cumulative += count
                    le = "+Inf" if bound == float("inf") else repr(bound)
                    lines.append(
                        f'aos_http_request_duration_seconds_bucket{{{labels},le="{le}"}} {cumulative}'
                    )
                lines.append(
                    f"aos_http_request_duration_seconds_sum{{{labels}}} {self.sums[(method, route)]:.6f}"
                )
                lines.append(f"aos_http_request_duration_seconds_count{{{labels}}} {cumulative}")
        return lines


http_metrics = HttpMetrics()


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _gauge(
    name: str, help_text: str, samples: list[tuple[dict[str, str], float]], kind: str = "gauge"
) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
    for labels, value in samples:
        rendered = ",".join(f'{k}="{_esc(v)}"' for k, v in sorted(labels.items()))
        lines.append(f"{name}{{{rendered}}} {value:g}" if rendered else f"{name} {value:g}")
    return lines


def workflow_metrics(db: Session) -> list[str]:
    now = func.now()
    runs = db.execute(select(Run.state, func.count()).group_by(Run.state)).all()
    jobs = db.execute(select(RunJob.state, func.count()).group_by(RunJob.state)).all()
    oldest_queued = db.scalar(
        select(func.coalesce(func.max(func.extract("epoch", now - RunJob.available_at)), 0)).where(
            RunJob.state == "QUEUED", RunJob.available_at <= now
        )
    )
    expired_leases = db.scalar(
        select(func.count())
        .select_from(RunJob)
        .where(RunJob.state == "LEASED", RunJob.lease_expires_at < now)
    )
    waiting = db.execute(
        select(
            RunJob.waiting_for,
            func.count(),
            func.coalesce(func.min(func.extract("epoch", RunJob.wait_deadline_at - now)), 0),
        )
        .where(RunJob.state == "WAITING")
        .group_by(RunJob.waiting_for)
    ).all()
    tools = db.execute(select(ToolExecution.status, func.count()).group_by(ToolExecution.status)).all()
    committed, uncertain = db.execute(
        select(
            func.coalesce(
                func.sum(func.coalesce(BudgetReservation.actual_cost, BudgetReservation.estimated_cost)), 0
            ),
            func.coalesce(
                func.sum(BudgetReservation.actual_cost).filter(BudgetReservation.uncertain.is_(True)), 0
            ),
        )
    ).one()
    tokens = db.execute(
        select(
            BudgetReservation.step,
            func.coalesce(func.sum(cast(BudgetReservation.usage["input_tokens"].astext, Float)), 0),
            func.coalesce(func.sum(cast(BudgetReservation.usage["output_tokens"].astext, Float)), 0),
        )
        .where(BudgetReservation.kind == "llm")
        .group_by(BudgetReservation.step)
    ).all()
    findings = db.execute(
        select(ReviewFindingRow.severity, ReviewFindingRow.source, func.count()).group_by(
            ReviewFindingRow.severity, ReviewFindingRow.source
        )
    ).all()

    lines: list[str] = []
    lines += _gauge("aos_runs", "Runs by workflow state.", [({"state": s}, n) for s, n in runs])
    lines += _gauge("aos_jobs", "Dispatch jobs by state.", [({"state": s}, n) for s, n in jobs])
    lines += _gauge(
        "aos_jobs_oldest_queued_seconds",
        "Age of the oldest runnable queued job.",
        [({}, float(oldest_queued or 0))],
    )
    lines += _gauge(
        "aos_jobs_expired_leases",
        "Leased jobs whose lease expired (a worker died or stalled).",
        [({}, float(expired_leases or 0))],
    )
    lines += _gauge(
        "aos_approvals_waiting",
        "Runs waiting for a human decision.",
        [({"kind": k or "?"}, n) for k, n, _ in waiting],
    )
    lines += _gauge(
        "aos_approvals_seconds_to_first_expiry",
        "Time until the earliest pending approval expires (negative: overdue, not yet swept).",
        [({"kind": k or "?"}, float(left)) for k, _, left in waiting],
    )
    lines += _gauge(
        "aos_tool_calls_total",
        "Recorded tool calls by status.",
        [({"status": s}, n) for s, n in tools],
        "counter",
    )
    lines += _gauge(
        "aos_budget_committed_usd_total",
        "Estimated spend committed across all runs (actuals, else reservations).",
        [({}, float(committed or 0))],
        "counter",
    )
    lines += _gauge(
        "aos_budget_uncertain_usd_total",
        "Spend that may have been billed but was never confirmed (crashes, failed calls).",
        [({}, float(uncertain or 0))],
        "counter",
    )
    lines += _gauge(
        "aos_llm_tokens_total",
        "Reconciled LLM tokens by workflow step and direction.",
        [({"step": s, "direction": "input"}, i) for s, i, _ in tokens]
        + [({"step": s, "direction": "output"}, o) for s, _, o in tokens],
        "counter",
    )
    lines += _gauge(
        "aos_review_findings_total",
        "Persisted review findings by severity and source.",
        [({"severity": sev, "source": src}, n) for sev, src, n in findings],
        "counter",
    )
    return lines
