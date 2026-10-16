# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: M11 (PRD Week 11), evaluation harness: DONE for fake agents. The live run
  waits for an API key and a written budget approval. Next: M12 local controlled pilot.

Last completed vertical slice:
  `python -m evaluation.run` drives every dev case through the real workflow for systems A
  (orchestrated), B (single-agent baseline) and C (reviewer ablation) on an isolated database,
  using the offline corpus and executable fault fixtures. A simulated human approves plans and
  reports. It writes per-run records, exported reports, and a summary with denominators and
  Wilson intervals. `python -m evaluation.blind` builds the blind human-scoring kit, and
  `evaluation.score` merges two scorers with Cohen's kappa.

Architecture decisions accepted:
  0010–0016 as before; 0017 evaluation harness, B/C definitions, simulated approvals, offline
  corpus with manifest hashes, guards for held-out and live runs, proxy-only automatic support
  metric, blind scoring.

Evaluation data:
  Dev set frozen: tag eval-dev-v1 (commit 37556c4). Held-out: 20 cases written after the
  freeze, before prompt tuning, by the system's author (recorded limitation); not yet run.
  Corpus v1: 80 documents (paraphrases of real docs, labelled as such, plus fictional
  .example products), per-case folders, MANIFEST.json hashes.

Database migrations added/applied:
  0001 … 0007 (M11 needed no schema change). Separate database `aos_eval` for harness runs.

Tests actually run and results (Windows, Python 3.14.7, PostgreSQL 17.11, Node 24.21):
  backend:  ruff + format clean; mypy --strict clean (app + evaluation); full pytest re-run
            for the M11 commit (see commit message for the count)
  evaluation: eval/results/2026-10-16-dev-validation-fake-16c073, 90 runs (20 cases x A/B/C
            + 3 repeats of 5 cases). FAKE-AGENT HARNESS VALIDATION, NOT A QUALITY RESULT:
            outcome matched expected in 28/30 runs per system; the 2 mismatches (dev-12,
            dev-13) are the fake writer drafting from a contact-sales or marketing page
            instead of stopping. Citation validity 100%. Injected URLs never fetched. Model
            faults ended FAILED with no report. $0 spent.
  frontend/e2e: unchanged since M10 (vitest 25, Playwright 5), re-run before commit
  CI:       M10 e8261f9 green on GitHub (per the user's screenshot)

Checks not run:
  Live model runs (no key; needs written budget approval). Held-out split (reserved).
  Human scoring, user interviews (project lead). docker compose up locally.

Known gaps (planned):
  live evaluation and human scoring (needs you); pilot packaging (M12); retention/deletion and
  audits (M13); load and backup/restore (M14); accessibility polish and user guide (M15);
  held-out rerun and final report (M16).

Next bounded task: M12. Production-like local profile (TLS reverse proxy notes, secrets
  guidance), migration and rollback procedure, seeded demo workspace with the planted-claim
  demo, onboarding notes, demo script, and the P0 acceptance checklist.
```