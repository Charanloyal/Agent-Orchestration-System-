# Evaluation plan

- **Status:** Plan only. No evaluation has been run, and no quality, latency or cost numbers
  exist yet.
- Targets in the PRD are proposed release gates, not results.

## Questions the evaluation must answer

1. Does the orchestrated four-agent workflow produce better-supported, better-covering reports
   than a single-agent baseline at comparable cost?
2. Does the reviewer contribute? Tested by a reviewer-removal ablation.
3. Does the system abstain correctly when evidence is missing, conflicting or stale, and resist
   malicious content and provider failures?

## Dataset

| Split | Count | Location | Status |
| --- | --- | --- | --- |
| Development | 20 | [eval/briefs/dev](../../eval/briefs/dev) | Written; validated by `test_contract_schemas.py` |
| Held-out | 20 | [eval/briefs/heldout](../../eval/briefs/heldout) | **Not written.** Procedure only, to avoid leakage |

Each case is an `EvalCase` ([schema](../contracts/eval-case.schema.json)): a `Brief`, a
category, and expectations. Expectations are a target outcome, `must_cover` coverage points and
`must_not` failure conditions. They are rubric anchors, **not gold answers**. No factual answers
are stored.

**Development category mix:**

| Category | Count |
| --- | --- |
| Answerable | 8 |
| Conflicting evidence | 3 |
| Unavailable evidence | 3 |
| Stale sources | 2 |
| Malicious content | 2 |
| Provider failure | 2 |

The held-out set should use the same mix.

Fixtures for fake providers (synthetic pages, injected failures) follow each case's
`fixture_notes`. They will be added with the fake search adapter in Week 4–5 and versioned
alongside the cases.

## Systems compared

| System | Description | Must match |
| --- | --- | --- |
| A: Orchestrated | Planner → researchers → writer → reviewer, with at most 2 review rounds | — |
| B: Single-agent baseline | One agent with the same tools that plans, researches and writes in one loop | Model, source corpus, brief, token/cost ceiling, tool allowlist |
| C: Reviewer ablation | System A with the reviewer removed (writer output goes straight to human approval) | Same as A |

## Metrics

| Metric | Definition | Method |
| --- | --- | --- |
| Citation validity | Share of cited evidence IDs that resolve to evidence authorized for the run | Automated (`validate_citations`) |
| Evidence support | Share of sampled verifiable claims fully supported by their cited passage | Blind human scoring; report the denominator and a 95% CI |
| Coverage | Share of `must_cover` points addressed | Human scoring |
| Uncertainty handling | Unknowns and conflicts labelled as such, not filled in | Human scoring (0/1 per occurrence) |
| Correct abstention | For unanswerable cases, a needs-attention outcome with an explanation | Automated outcome + human check |
| `must_not` violations | Any listed failure behaviour | Human scoring; any violation fails the case |
| Latency | Wall-clock time from brief submission to a reviewable draft, excluding human wait time | Automated |
| Cost | Reconciled provider cost per run (median and p95) and the price schedule used | Cost ledger |
| Reviewer effort | Minutes a human reviewer spends to approve or reject | Self-timed, recorded per case |
| Operational failure rate | Runs ending FAILED for non-brief reasons | Automated |

Report answerable and unanswerable cases separately.

## Scoring procedure

1. Run every system on every case with fixed model and provider versions, recorded in the
   results. Repeat a subset of 5 cases 3 times to show output variability.
2. Strip system identity from reports and shuffle the order before human scoring (blind).
3. Two scorers independently score a random sample of at least 30 claims per system. Resolve
   disagreements, and report the agreement rate.
4. Model-based judging may triage, but is never the sole authority for support or correctness.
5. Store raw outputs, scores and configuration under `eval/results/<date>-<run-id>/`, without
   secrets or full copyrighted source text.

## Leakage rules

- Tune prompts, thresholds and routing only on the **development** split.
- Run the held-out split only at the Week-11 evaluation and the Week-16 release review.
- Any change made after seeing held-out results invalidates that held-out run for claims.

## Live-provider runs

Live model and search calls need an explicit budget approved under
[ADR 0005](../decisions/0005-spending-ceiling.md). Results from live runs are labelled
separately from fake-provider runs.
