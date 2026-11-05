# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: M3–M16 DONE on the repository side. M16 (final report) is written
  from measured results only: docs/report/final-report.md and appendices.md. Nothing is
  in progress. Remaining work needs the project lead (see Known gaps).

Last completed slice (M16):
  Final report with 19 sections; architecture, state, sequence and ER diagrams; 29
  references, each checked against arXiv, Crossref or the publisher on 2026-11-04;
  dataset hashes (dev e9b07361…, held-out 828c4882…, corpus manifest 967f7c06…,
  unchanged since M11). The live and held-out evaluation is marked BLOCKED, at the project
  lead's choice on 2026-11-04 (no API key, no budget approval, no human scorers). The
  held-out set has still never been run.

Previous slice (M15):
  Run page workflow stepper (responsive grid on phones), admin "Delete run" with
  confirmation, admin Activity page over the append-only audit log, a "Demo agents" badge
  driven by /api/v1/auth/me `deployment.agent_mode`, a skip link, per-page document titles and
  a compact mobile top bar. docs/user-guide.md embeds 12 screenshots captured from the real
  stack by frontend/e2e/screenshots.spec.ts (AOS_SCREENSHOTS=1); docs/troubleshooting.md
  maps real error messages and log lines to fixes.

Earlier slices (M12–M14):
  The single-origin image (API serves the SPA; same image runs the worker; no dev issuer)
  and render.yaml (web + worker + managed Postgres, schema-validated). Production refuses
  unsafe settings and needs an allowlist. /readyz requires the migration head; the worker
  waits for migrations and survives database outages. Admin run deletion and a retention
  sweep; append-only audit. Load test, crash takeover and a backup/restore drill
  (docs/operations/load-and-recovery.md).

Architecture decisions accepted:
  0001–0017 as before; 0018 single-origin image, Render topology, production hardening;
  0019 data lifecycle and append-only audit log.

Database migrations:
  0001 … 0008 (0008: audit_events append-only trigger). Dev DB `aos` at 0008.

Tests actually run for M15 (Windows, Python 3.14.7, PostgreSQL 17.11, Node 24.21):
  backend ruff + format + mypy clean, pytest 398 passed / 1 live test deselected; frontend
  typecheck clean, vitest 35 passed, build OK, Playwright 6 passed (plus the opt-in
  screenshot spec). M14 measurements: 20 readers p95 158 ms, 0 errors; 10 concurrent
  workflows with 0 integrity or isolation violations; crash takeover 5.89 s with a 6 s
  lease; graceful stop 0.6–0.7 s; restore drill PASS.

Checks not run:
  Docker builds (no Docker locally; CI `containers` and `deploy-image` jobs build and
  smoke-test them). Render deployment (no account access; manual steps in
  docs/operations/deploy-render.md). Live-model evaluation (needs a key and a budget).
  Screen-reader testing with real assistive technology.

Known gaps (need the project lead):
  1. Live evaluation: put a key in backend/.env, approve a budget of at most USD 10 in
     writing, then follow docs/evaluation/evaluation-plan.md "Live run checklist": smoke
     run, dev split, then the held-out split once.
  2. Blind human scoring with two scorers (python -m evaluation.blind / evaluation.score).
  3. User interviews (docs/product/interview-guide.md).
  4. Render deployment (docs/operations/deploy-render.md): account, payment, a real OIDC
     provider, allowlist, first admin.
  After 1–2, update report sections 13.5, 14 and 17 with the measured results only.
```