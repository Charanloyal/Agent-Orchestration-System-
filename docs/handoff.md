# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: M5 (PRD Week 5), ingestion & evidence: DONE. Next: M6 planner (real LLM) + plan approval UX.

Last completed vertical slice:
  Analyst signs in → submits a brief → worker plans (fake planner) → analyst approves the exact
  plan version → worker researches (fake search, evidence stored with provenance), drafts a
  cited report, reviews it → reviewer signs in, inspects cited passages, approves the exact
  report version → SUCCEEDED. Live SSE timeline survives reloads (Last-Event-ID replay).
  Verified in a real browser and by Playwright.

Architecture decisions accepted:
  0010 workflow runtime, live events, frontend architecture; 0011 evidence ingestion
  (Tavily/corpus/fake search, SSRF-pinned fetcher, isolated PDF extraction, uploads, Postgres FTS).

Database migrations added/applied:
  0002_runs_jobs_events_artifacts_evidence (briefs, runs, run_jobs, run_events, plan_versions,
  report_versions, approvals, tool_executions, sources, evidence_passages, task_results; schema
  `lg` for LangGraph checkpoints); 0003_uploads_and_full_text_search (uploads, upload_chunks with
  generated tsvector + GIN; evidence_passages.tsv). Applied to dev DB `aos`; test/e2e DBs rebuilt per run.

Tests actually run and results (2026-10-15, Windows, Python 3.14.7, PostgreSQL 17.11, Node 24.21):
  backend:  ruff + format clean; mypy --strict clean (55 files); pytest 192 passed
            (incl. route-generated authz matrix now covering run/report routes, workflow API
            tests driving the real worker, 3 subprocess crash windows, stale-owner checkpoint
            fencing with negative control, retry/fail classification, tool-allowlist policy)
  frontend: tsc (app + e2e) clean; vitest 15 passed; vite build OK
  e2e:      Playwright (installed Edge) 2 passed: full analyst→reviewer journey with reload,
            and cross-workspace 404, against an isolated dev IdP + API + worker + Vite + Postgres
  CI:       M3 run green on GitHub (backend, spike, frontend, container builds)

Checks not run:
  docker compose up locally (no Docker); images are built in CI.
  User interviews; blind human scoring (project lead).

Observed performance/cost: none measured; no provider cost (fake agents only).

Known gaps (planned):
  Real LLM agents (M6/M8), offline evaluation corpus content (M11), budgets (M7), cancel/retry
  APIs + 10-scenario crash suite + reaper + approval expiry (M9), observability (M10),
  export (M8), evaluation (M11).

Next bounded task: M6. OpenAI-compatible LLM adapter with structured output + one bounded
  repair, versioned planner prompt, plan edit-as-new-version, approval-wait expiry (EXPIRED),
  plan review UI polish. Live calls only after explicit approval within the USD 10 ceiling.
```
