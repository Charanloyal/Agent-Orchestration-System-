# 0017: Evaluation harness, systems A/B/C, offline corpus and blind scoring

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** PRD §4 (evaluation), [evaluation plan](../evaluation/evaluation-plan.md),
  ADR 0005 (spending ceiling)

## Context

The evaluation plan defined three systems, metrics and leakage rules, but nothing ran yet.
There was no corpus, no held-out set, and no way to reproduce a fixture such as "search
returns 429 twice". Live model runs cost money and need approval, and no API key has been
supplied yet. The harness therefore had to be complete and verifiable without paid calls,
and honest about what fake-agent numbers can and cannot show.

## Decisions

1. **The dev set is frozen** with the tag `eval-dev-v1` (commit `37556c4`). The **held-out
   set** (20 cases, same category mix, new topics) was written afterwards by the system's
   author, before any prompt tuning. This limitation is recorded in
   [eval/briefs/heldout/README.md](../../eval/briefs/heldout/README.md).
2. **Offline corpus v1 (`eval/corpus/v1`).**
   - It holds 80 short documents written for this project, one folder per case.
   - Real topics are *paraphrases*, labelled as such, with the source URL for verification.
     Invented products use `.example` domains. No vendor text is copied.
   - A `MANIFEST.json` with SHA-256 hashes is checked by tests, and the manifest hash is
     recorded with every result set.
   - Prose `fixture_notes` become executable `fixture.json` files: search faults, model
     faults, and workspace uploads.
3. **Systems** (`backend/evaluation/systems.py`):
   - **A:** the production suite.
   - **B, single-agent baseline:** same tools, corpus, budget and allowlist; a fixed one-task
     plan; deterministic collection for every research question; one writer call; no
     reviewer.
   - **C:** A with a pass-through reviewer.
   - All systems run through the real workflow (leases, budgets, citation validation, human
     gates), via a new `agent_factory` hook on `process_one`.
4. **Simulated human.** The harness approves every plan and report automatically, and records
   this in `config.json` and on each run. Transient-error backoff is skipped but measured.
   Latency excludes both.
5. **Isolation and safety.**
   - Each run gets a fresh workspace, so uploads cannot leak between cases.
   - A network-refusing fetcher records any fetch attempt.
   - The database is a dedicated one (`AOS_EVAL_DATABASE_URL`).
   - Held-out runs need `--confirm-heldout`.
   - Live runs need `--live --budget ≤ 10`, stop when the budget is reached, and record
     their spend.
   - Offline search providers (`fake`, `corpus`) are never priced. Before this fix, a failed
     corpus search left an "uncertain" estimate for money that was never at stake.
6. **Metrics** (`backend/evaluation/metrics.py`):
   - Automated: outcome vs expected (correct abstention or safe failure), operational
     failures, citation validity, real review rounds (pass-through rounds counted
     separately), latency, cost, and mechanical `must_not` checks (no fetch attempted, human
     gate not bypassed, no unsupported figures, no source older than the cutoff cited, no
     report after a model failure).
   - Every proportion carries its denominator and a Wilson 95% interval. Results are split
     into answerable and unanswerable/adversarial cases.
   - The deterministic support check is reported only as a **proxy**.
7. **Blind human scoring** (`evaluation.blind`, `evaluation.score`):
   - Shuffled reports under blind IDs, with the unblinding key kept separate.
   - Sampled claims shown with their cited passages, plus coverage and `must_not` sheets.
   - Two-scorer merge reports raw agreement and Cohen's κ, and lists disagreements for
     adjudication instead of averaging them away.
   - Model-based judging is not used.

## Consequences

- The committed run `eval/results/2026-10-16-dev-validation-fake-16c073` (90 runs) is
  labelled **harness validation, not a quality result**.
  - It shows the fixtures behave as designed: the injected URL is never fetched, provider
    failures end FAILED with no report, 429s are retried, and stale sources are filtered.
  - It also shows a real limitation of the deterministic agents: for dev-12 and dev-13 they
    draft a report from a "contact sales" page or a marketing page instead of stopping for
    attention.
- Quality claims (A vs B vs C) require the live run and blind human scoring. The live run
  needs an API key and an approved budget.
- A synthetic corpus measures orchestration behaviour, not open-web research quality. This is
  a stated threat to validity.
