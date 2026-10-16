"""M11: evaluation data, harness, metrics, blinding and scoring (ADR 0017)."""

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.contracts.evaluation import EvalCase
from app.db.models import User
from app.providers.corpus import CorpusDocument
from evaluation.blind import blind, write_csv
from evaluation.cases import BRIEFS_DIR, CORPUS_DIR, load_cases
from evaluation.harness import FAKE_LABEL, EvaluationConfig, run_evaluation
from evaluation.metrics import cohen_kappa, observed_outcome, outcome_matches, wilson
from evaluation.score import merge

MIX = {
    "answerable": 8,
    "conflicting_evidence": 3,
    "unavailable_evidence": 3,
    "stale_sources": 2,
    "malicious_content": 2,
    "provider_failure": 2,
}


# --- Data ------------------------------------------------------------------------------------


@pytest.mark.parametrize("split", ["dev", "heldout"])
def test_split_has_twenty_valid_cases_with_the_planned_mix(split: str) -> None:
    cases = [
        EvalCase.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((BRIEFS_DIR / split).glob(f"{split}-*.json"))
    ]
    assert len(cases) == 20 and all(c.split == split for c in cases)
    assert Counter(c.category for c in cases) == MIX


def test_heldout_topics_do_not_reuse_dev_topics() -> None:
    dev = {c.case.brief.topic.casefold() for c in load_cases("dev")}
    assert not dev & {c.case.brief.topic.casefold() for c in load_cases("heldout")}


def test_corpus_covers_every_case_and_matches_its_manifest() -> None:
    manifest = json.loads((CORPUS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    cases = load_cases("dev") + load_cases("heldout")
    assert set(manifest["cases"]) == {c.case_id for c in cases}
    for fixture in cases:
        entries = manifest["cases"][fixture.case_id]["documents"]
        files = sorted(fixture.docs_dir.glob("*.json")) if fixture.docs_dir.exists() else []
        assert len(files) == len(entries), fixture.case_id
        for entry in entries:
            raw = (fixture.docs_dir / f"{entry['doc_id']}.json").read_bytes()
            assert hashlib.sha256(raw).hexdigest() == entry["sha256"], f"{entry['doc_id']} changed"
            doc = CorpusDocument(**json.loads(raw))
            assert "AOS evaluation corpus v1" in doc.attribution
            assert entry["kind"] in ("paraphrase", "fictional")
            if entry["kind"] == "fictional":
                assert ".example/" in doc.url or doc.url.endswith(".example"), (
                    "invented products use .example"
                )
            else:
                assert doc.title.endswith("(paraphrase)")


# Documents deliberately outside their case's source policy, to test that it is enforced.
OFF_POLICY_PROBES = {("dev-02", "dedicated-engine-ops")}


def test_corpus_documents_respect_their_case_source_policy() -> None:
    from app.tools.policy import domain_permitted

    off_policy = set()
    for fixture in load_cases("dev") + load_cases("heldout"):
        for path in sorted(fixture.docs_dir.glob("*.json")) if fixture.docs_dir.exists() else []:
            doc = CorpusDocument(**json.loads(path.read_text("utf-8")))
            if not domain_permitted(doc.url, fixture.case.brief.source_policy):
                off_policy.add((fixture.case_id, doc.doc_id))
    assert off_policy == OFF_POLICY_PROBES


def test_fixture_notes_are_machine_readable_where_the_harness_needs_them() -> None:
    by_id = {c.case_id: c for c in load_cases("dev") + load_cases("heldout")}
    assert by_id["dev-19"].search_fault is not None and by_id["dev-19"].search_fault.times == 2
    assert by_id["dev-20"].model_fault == "http_500" and by_id["heldout-20"].model_fault == "timeout"
    assert any("SYSTEM:" in u.text for u in by_id["dev-18"].uploads)
    assert by_id["heldout-13"].docs_dir.exists() is False or not list(
        by_id["heldout-13"].docs_dir.glob("*.json")
    )


# --- Metrics ---------------------------------------------------------------------------------


def test_wilson_interval_matches_reference_values() -> None:
    low, high = wilson(8, 10)  # type: ignore[misc]
    assert round(low, 3) == 0.490 and round(high, 3) == 0.943
    assert wilson(0, 0) is None
    low, high = wilson(0, 20)  # type: ignore[misc]
    assert low == 0.0 and 0.15 < high < 0.17


def test_cohen_kappa() -> None:
    assert cohen_kappa(["1", "0", "1"], ["1", "0", "1"]) == 1.0
    assert cohen_kappa(["1", "1", "0", "0"], ["1", "0", "1", "0"]) == 0.0
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["1", "1"], ["1", "1"]) is None, "undefined when chance agreement is total"
    with pytest.raises(ValueError):
        cohen_kappa(["1"], [])


@pytest.mark.parametrize(
    ("expected", "state", "reached", "has_report", "matches"),
    [
        ("reviewable_draft", "SUCCEEDED", True, True, True),
        ("reviewable_draft", "NEEDS_ATTENTION", False, False, False),
        ("needs_attention_with_explanation", "NEEDS_ATTENTION", False, False, True),
        ("needs_attention_with_explanation", "SUCCEEDED", True, True, False),
        ("failed_safely", "FAILED", False, False, True),
        ("failed_safely", "FAILED", False, True, False),
    ],
)
def test_outcome_mapping(expected: str, state: str, reached: bool, has_report: bool, matches: bool) -> None:
    assert outcome_matches(expected, observed_outcome(state, reached, has_report)) is matches


# --- Harness end to end (fake agents, test database) -----------------------------------------


@pytest.fixture
def harness_results(
    tmp_path: Path, db: Any, checkpointer_ready: None, make_user: Callable[..., User]
) -> tuple[Path, list[dict[str, Any]]]:
    fixtures = load_cases("dev", ["dev-01", "dev-17", "dev-19", "dev-20"])
    config = EvaluationConfig(
        split="dev",
        systems=["A", "B", "C"],
        case_ids=[f.case_id for f in fixtures],
        repeats=2,
        repeat_case_ids=["dev-01"],
        mode="fake",
    )
    out = run_evaluation(get_settings(), fixtures, config, tmp_path, label="test")
    records = [json.loads(line) for line in (out / "runs.jsonl").read_text("utf-8").splitlines()]
    return out, records


def test_harness_runs_every_case_and_system_and_records_honest_metadata(
    harness_results: tuple[Path, list[dict[str, Any]]],
) -> None:
    out, records = harness_results
    assert len(records) == 3 * 3 + 3 * 2, "dev-01 repeated twice per system"
    meta = json.loads((out / "config.json").read_text("utf-8"))
    assert meta["label"] == FAKE_LABEL and "automatically" in meta["simulated_human"]
    assert meta["settings"]["agent_mode"] == "fake" and len(meta["git"]["commit"]) == 40
    summary = (out / "summary.md").read_text("utf-8")
    assert FAKE_LABEL in summary and "95% CI" in summary
    by_key = {r["key"]: r for r in records}

    for system in "ABC":
        answerable = by_key[f"dev-01__{system}__r1"]
        assert (
            answerable["observed_outcome"] == "reviewable_draft" and answerable["final_state"] == "SUCCEEDED"
        )
        assert answerable["report"]["citations"] == answerable["report"]["valid_citations"] > 0
        assert answerable["simulated_decisions"] == ["plan:approve", "report:approve"]
        assert all(answerable["must_not_checks"].values())
        assert (out / "reports" / f"dev-01__{system}__r1.md").exists()

        injected = by_key[f"dev-17__{system}__r1"]
        assert injected["must_not_checks"]["no_network_fetch_attempted"], "injected URL never fetched"

        flaky = by_key[f"dev-19__{system}__r1"]
        # Two injected 429s may hit parallel tasks in the same pass, so 1 or 2 retries.
        assert 1 <= flaky["transient_retries"] <= 2 and flaky["observed_outcome"] == "reviewable_draft"

        failing = by_key[f"dev-20__{system}__r1"]
        assert failing["final_state"] == "FAILED" and failing["outcome_matches"]
        assert (
            failing["must_not_checks"]["no_report_after_model_failure"] and not failing["operational_failure"]
        )

    assert by_key["dev-01__B__r1"]["states"].count("PLANNING") == 1
    assert by_key["dev-01__A__r1"]["review"]["rounds"] == 1
    for ablated in ("B", "C"):
        review = by_key[f"dev-01__{ablated}__r1"]["review"]
        assert review["rounds"] == 0 and review["pass_through_rounds"] == 1, "no real review in B or C"
    assert all(r["cost"]["committed"] in ("0", "0.000000") for r in records), "offline corpus is free"
    summary_json = json.loads((out / "summary.json").read_text("utf-8"))
    assert set(summary_json) == {"A", "B", "C"}
    assert summary_json["A"]["answerable"]["runs"] == 2


def test_blind_kit_hides_system_identity_and_scores_merge_with_agreement(
    harness_results: tuple[Path, list[dict[str, Any]]],
) -> None:
    out, records = harness_results
    scoring = blind(out, claims_per_system=5, seed=7)
    key = json.loads((scoring / "KEY.json").read_text("utf-8"))
    with_reports = [r for r in records if r["report"]["versions"]]
    assert len(key) == len(with_reports)
    assert {v["key"] for v in key.values()} == {r["key"] for r in with_reports}
    for path in (scoring / "reports").iterdir():
        assert path.stem in key and "__" not in path.name
    for name in ("claims.csv", "coverage.csv", "must_not.csv"):
        text = (scoring / name).read_text("utf-8")
        assert "__A__" not in text and "__B__" not in text and "__C__" not in text
    with (scoring / "claims.csv").open(encoding="utf-8") as handle:
        claims = list(csv.DictReader(handle))
    assert claims and Counter(key[c["blind_id"]]["system"] for c in claims).most_common(1)[0][1] <= 5

    scorer_a, scorer_b = scoring / "a", scoring / "b"
    for folder, flip in ((scorer_a, False), (scorer_b, True)):
        folder.mkdir()
        filled = [dict(c, support="full", scorer=folder.name) for c in claims]
        if flip:
            filled[0]["support"] = "none"
        write_csv(folder / "claims.csv", filled)
    merged = merge(scoring, scorer_a, scorer_b)
    agreement = merged["agreement"]["claims.csv"]
    assert agreement["items_scored_by_both"] == len(claims)
    assert agreement["raw_agreement"]["successes"] == len(claims) - 1
    assert merged["disagreements"][0]["a"] == "full" and merged["disagreements"][0]["b"] == "none"
