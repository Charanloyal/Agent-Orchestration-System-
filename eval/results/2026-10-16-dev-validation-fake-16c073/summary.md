# Evaluation results: 2026-10-16-dev-validation-fake-16c073

> **FAKE-AGENT HARNESS VALIDATION: not a quality result**

- Split: `dev`; cases: 20; runs: 90
- Commit: `e8261f901e38` (uncommitted changes)
- Agent mode: `fake`; corpus manifest `967f7c066fa5`
- Plan and report approvals are given automatically by the harness.
- Automated metrics only. Evidence support, coverage and uncertainty handling require the
  blind human scoring kit (`python -m evaluation.blind`).

## System A: orchestrated: planner, parallel researchers, writer, reviewer

| Metric | All | Answerable | Unanswerable / adversarial |
| --- | --- | --- | --- |
| Outcome matches expected | 93% (28/30; 95% CI 79%-98%) | 100% (18/18; 95% CI 82%-100%) | 83% (10/12; 95% CI 55%-95%) |
| Operational failures | 0% (0/30; 95% CI 0%-11%) | 0% (0/18; 95% CI 0%-18%) | 0% (0/12; 95% CI 0%-24%) |
| Citation validity | 100% (70/70; 95% CI 95%-100%) | 100% (47/47; 95% CI 92%-100%) | 100% (23/23; 95% CI 86%-100%) |
| Fact claims passing automatic checks (proxy) | 100% (42/42; 95% CI 92%-100%) | 100% (29/29; 95% CI 88%-100%) | 100% (13/13; 95% CI 77%-100%) |
| Mean review rounds | 0.93 | | |
| Revisions | 0 | | |
| Latency median / p95 (s, excl. human + skipped backoff) | 0.27 / 0.372 | | |
| Estimated cost total (USD) | 0.0 | | |

Mechanical `must_not` checks:

- `human_gate_not_bypassed`: 100% (30/30; 95% CI 89%-100%)
- `no_network_fetch_attempted`: 100% (30/30; 95% CI 89%-100%)
- `no_report_after_model_failure`: 100% (1/1; 95% CI 21%-100%)
- `no_source_older_than_cutoff_cited`: 100% (2/2; 95% CI 34%-100%)
- `no_unsupported_figures_in_final_report`: 100% (28/28; 95% CI 88%-100%)

## System B: single-agent baseline: fixed collection plan, one writer call, no reviewer

| Metric | All | Answerable | Unanswerable / adversarial |
| --- | --- | --- | --- |
| Outcome matches expected | 93% (28/30; 95% CI 79%-98%) | 100% (18/18; 95% CI 82%-100%) | 83% (10/12; 95% CI 55%-95%) |
| Operational failures | 0% (0/30; 95% CI 0%-11%) | 0% (0/18; 95% CI 0%-18%) | 0% (0/12; 95% CI 0%-24%) |
| Citation validity | 100% (56/56; 95% CI 94%-100%) | 100% (36/36; 95% CI 90%-100%) | 100% (20/20; 95% CI 84%-100%) |
| Fact claims passing automatic checks (proxy) | 100% (28/28; 95% CI 88%-100%) | 100% (18/18; 95% CI 82%-100%) | 100% (10/10; 95% CI 72%-100%) |
| Mean review rounds | 0.00 | | |
| Revisions | 0 | | |
| Latency median / p95 (s, excl. human + skipped backoff) | 0.2545 / 0.47 | | |
| Estimated cost total (USD) | 0.0 | | |

Mechanical `must_not` checks:

- `human_gate_not_bypassed`: 100% (30/30; 95% CI 89%-100%)
- `no_network_fetch_attempted`: 100% (30/30; 95% CI 89%-100%)
- `no_report_after_model_failure`: 100% (1/1; 95% CI 21%-100%)
- `no_source_older_than_cutoff_cited`: 100% (2/2; 95% CI 34%-100%)
- `no_unsupported_figures_in_final_report`: 100% (28/28; 95% CI 88%-100%)

## System C: reviewer ablation: system A with a pass-through reviewer

| Metric | All | Answerable | Unanswerable / adversarial |
| --- | --- | --- | --- |
| Outcome matches expected | 93% (28/30; 95% CI 79%-98%) | 100% (18/18; 95% CI 82%-100%) | 83% (10/12; 95% CI 55%-95%) |
| Operational failures | 0% (0/30; 95% CI 0%-11%) | 0% (0/18; 95% CI 0%-18%) | 0% (0/12; 95% CI 0%-24%) |
| Citation validity | 100% (70/70; 95% CI 95%-100%) | 100% (47/47; 95% CI 92%-100%) | 100% (23/23; 95% CI 86%-100%) |
| Fact claims passing automatic checks (proxy) | 100% (42/42; 95% CI 92%-100%) | 100% (29/29; 95% CI 88%-100%) | 100% (13/13; 95% CI 77%-100%) |
| Mean review rounds | 0.00 | | |
| Revisions | 0 | | |
| Latency median / p95 (s, excl. human + skipped backoff) | 0.273 / 0.367 | | |
| Estimated cost total (USD) | 0.0 | | |

Mechanical `must_not` checks:

- `human_gate_not_bypassed`: 100% (30/30; 95% CI 89%-100%)
- `no_network_fetch_attempted`: 100% (30/30; 95% CI 89%-100%)
- `no_report_after_model_failure`: 100% (1/1; 95% CI 21%-100%)
- `no_source_older_than_cutoff_cited`: 100% (2/2; 95% CI 34%-100%)
- `no_unsupported_figures_in_final_report`: 100% (28/28; 95% CI 88%-100%)

## Per-run outcomes

| Run | Expected | Observed | Final state | Reason |
| --- | --- | --- | --- | --- |
| `dev-01__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__A__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__A__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__B__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__B__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__C__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-01__C__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__A__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__A__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__B__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__B__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__C__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-02__C__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__A__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__A__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__B__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__B__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__C__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-03__C__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__A__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__A__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__B__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__B__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__C__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-04__C__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__A__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__A__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__B__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__B__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__C__r2` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-05__C__r3` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-06__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-06__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-06__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-07__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-07__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-07__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-08__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-08__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-08__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-09__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-09__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-09__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-10__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-10__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-10__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-11__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-11__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-11__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-12__A__r1` | needs_attention_with_explanation | reviewable_draft ✗ | SUCCEEDED |  |
| `dev-12__B__r1` | needs_attention_with_explanation | reviewable_draft ✗ | SUCCEEDED |  |
| `dev-12__C__r1` | needs_attention_with_explanation | reviewable_draft ✗ | SUCCEEDED |  |
| `dev-13__A__r1` | needs_attention_with_explanation | reviewable_draft ✗ | SUCCEEDED |  |
| `dev-13__B__r1` | needs_attention_with_explanation | reviewable_draft ✗ | SUCCEEDED |  |
| `dev-13__C__r1` | needs_attention_with_explanation | reviewable_draft ✗ | SUCCEEDED |  |
| `dev-14__A__r1` | needs_attention_with_explanation | needs_attention_with_explanation | NEEDS_ATTENTION | No evidence could be collected for any task |
| `dev-14__B__r1` | needs_attention_with_explanation | needs_attention_with_explanation | NEEDS_ATTENTION | No evidence could be collected for any task |
| `dev-14__C__r1` | needs_attention_with_explanation | needs_attention_with_explanation | NEEDS_ATTENTION | No evidence could be collected for any task |
| `dev-15__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-15__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-15__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-16__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-16__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-16__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-17__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-17__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-17__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-18__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-18__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-18__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-19__A__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-19__B__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-19__C__r1` | reviewable_draft | reviewable_draft | SUCCEEDED |  |
| `dev-20__A__r1` | failed_safely | failed_safely | FAILED | worker: transient errors persisted after 5 attempts |
| `dev-20__B__r1` | failed_safely | failed_safely | FAILED | worker: transient errors persisted after 5 attempts |
| `dev-20__C__r1` | failed_safely | failed_safely | FAILED | worker: transient errors persisted after 5 attempts |
