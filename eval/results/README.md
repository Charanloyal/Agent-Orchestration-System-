# Evaluation results

One folder per harness invocation, named `<date>-<label>-<mode>-<id>`, written by
`python -m evaluation.run` ([ADR 0017](../../docs/decisions/0017-evaluation-harness.md)).

| File | Contents |
| --- | --- |
| `config.json` | Git commit (and whether the tree was dirty), split, cases, systems, repeats, agent mode, model, price schedule, corpus manifest hash, live budget and spend, start and finish times |
| `runs.jsonl` | One record per case × system × repeat: expected vs observed outcome, states, retries, latency, citations, automatic checks, review rounds, tools, evidence, cost, mechanical `must_not` checks |
| `summary.json`, `summary.md` | Per-system aggregates with denominators and Wilson 95% intervals, split into answerable and unanswerable cases |
| `reports/*.md` | The exported Markdown report of every run that produced one |
| `artifacts/*.json` | Final report body and cited passages (synthetic corpus text), used by the blind scoring kit |

## Read the label first

- **`FAKE-AGENT HARNESS VALIDATION: not a quality result`**: deterministic fake agents.
  These runs show the harness, fixtures and metrics work end to end. Systems A, B and C
  differ only mechanically (B has a fixed plan and no reviewer; C has no reviewer), so these
  numbers say **nothing** about report quality or about whether orchestration helps.
- **`LIVE-PROVIDER RUN`**: a real model within an approved budget. Its automated metrics are
  valid as measured. Evidence support, coverage and uncertainty handling still need the blind
  human scoring (`python -m evaluation.blind`, then `python -m evaluation.score`).

Approvals in every run come from a *simulated human* that approves automatically. Reviewer
effort is measured only by the human scorers.

## Current folders

| Folder | Split | Mode | Notes |
| --- | --- | --- | --- |
| `2026-10-16-dev-validation-fake-16c073` | dev | fake | 20 cases × A/B/C, 3 repeats of 5 answerable cases (90 runs). Harness validation only |
