# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: M12–M15 DONE on the repository side (pilot packaging; retention,
  deletion, audit; reliability, load and recovery; UX, accessibility, user docs).
  Next: M16 final report.

Last completed vertical slice (M15):
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

Known gaps:
  M16 final report. Live evaluation, held-out run, human scoring and user interviews need
  the project lead.
```