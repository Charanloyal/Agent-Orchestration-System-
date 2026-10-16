"""Evaluation metrics (docs/evaluation/evaluation-plan.md). Pure functions over run records.

Automated metrics are reported with their denominators and Wilson 95% intervals. Metrics
that need human judgement (evidence support, coverage, uncertainty handling) come from the
blind scoring sheets; the automatic support check here is labelled as a *proxy* only.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

ANSWERABLE = "answerable"


def wilson(successes: int, total: int, z: float = 1.959964) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion; None when there is no data."""
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion(successes: int, total: int) -> dict[str, Any]:
    interval = wilson(successes, total)
    return {
        "successes": successes,
        "total": total,
        "rate": (successes / total) if total else None,
        "ci95": [round(interval[0], 4), round(interval[1], 4)] if interval else None,
    }


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Agreement between two scorers beyond chance. None when undefined (no items, or both
    scorers used a single identical label for everything)."""
    if len(a) != len(b):
        raise ValueError("scorers rated different numbers of items")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    labels = set(a) | set(b)
    expected = sum((a.count(label) / n) * (b.count(label) / n) for label in labels)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def observed_outcome(final_state: str, reached_report: bool, has_report: bool) -> str:
    """Map a run's end state onto the evaluation's expected-outcome vocabulary."""
    if reached_report:
        return "reviewable_draft"
    if final_state == "NEEDS_ATTENTION":
        return "needs_attention_with_explanation" if has_report is False else "needs_attention_with_report"
    if final_state == "FAILED":
        return "failed_safely" if not has_report else "failed_after_report"
    return final_state.lower()


def outcome_matches(expected: str, observed: str) -> bool:
    if expected == "failed_safely":
        # A visible stop without an invented report is the safe outcome either way.
        return observed in ("failed_safely", "needs_attention_with_explanation")
    if expected == "needs_attention_with_explanation":
        return observed in ("needs_attention_with_explanation", "needs_attention_with_report")
    return observed == expected


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def _group_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    with_report = [r for r in records if r["report"]["claims"] > 0]
    citations = sum(r["report"]["citations"] for r in with_report)
    valid = sum(r["report"]["valid_citations"] for r in with_report)
    facts = sum(r["report"]["fact_claims"] for r in with_report)
    supported = sum(r["report"]["fact_claims_passing_checks"] for r in with_report)
    checks: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        for name, passed in r["must_not_checks"].items():
            checks[name].append(bool(passed))
    latencies = [r["latency_seconds"] for r in records if r["latency_seconds"] is not None]
    costs = [float(r["cost"]["committed"]) for r in records]
    return {
        "runs": n,
        "outcome_matches_expected": proportion(sum(r["outcome_matches"] for r in records), n),
        "operational_failures": proportion(sum(r["operational_failure"] for r in records), n),
        "citation_validity": proportion(valid, citations),
        "fact_claims_passing_automatic_checks_PROXY": proportion(supported, facts),
        "mechanical_must_not_checks": {
            name: proportion(sum(v), len(v)) for name, v in sorted(checks.items())
        },
        "review_rounds_mean": statistics.fmean(r["review"]["rounds"] for r in records) if records else None,
        "revisions_total": sum(max(0, r["report"]["versions"] - 1) for r in records),
        "latency_seconds": {
            "median": statistics.median(latencies) if latencies else None,
            "p95": _quantile(latencies, 0.95),
        },
        "cost_usd": {
            "median": statistics.median(costs) if costs else None,
            "p95": _quantile(costs, 0.95),
            "total": round(sum(costs), 6),
        },
    }


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Per system, split into answerable and unanswerable cases as the plan requires."""
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_system[record["system"]].append(record)
    summary: dict[str, Any] = {}
    for system, items in sorted(by_system.items()):
        answerable = [r for r in items if r["category"] == ANSWERABLE]
        other = [r for r in items if r["category"] != ANSWERABLE]
        summary[system] = {
            "all": _group_summary(items),
            "answerable": _group_summary(answerable),
            "unanswerable_or_adversarial": _group_summary(other),
        }
    return summary
