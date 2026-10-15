# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: M3 (PRD Week 3), backend foundation: DONE. Next: M4 thin end-to-end slice.

Last completed vertical slice:
  Browser → Vite proxy → FastAPI → dev OIDC issuer (code + PKCE) → callback → server-side
  session → /api/v1/auth/me shows the seeded workspace role. Verified in a real browser.

Architecture decisions accepted:
  0002 OpenAI-compatible LLM adapter; 0003 Tavily + offline corpus; 0004 local
  production-like deployment; 0005 USD 10 ceiling; 0009 identity/sessions/authorization.

Database migrations added/applied:
  0001_identity_and_tenancy (workspaces, users, memberships, auth_sessions,
  oidc_login_states, audit_events). Applied to local dev DB `aos`; test DB rebuilt per run.

Tests actually run and results (2026-10-15, Windows, Python 3.14.7, PostgreSQL 17.11):
  backend: ruff check + format clean; mypy --strict: no issues (39 files);
           pytest: 150 passed (contracts, schema drift, migrations up/down + model drift,
           OIDC end-to-end against the real dev issuer + ID-token negatives,
           route-generated authz matrix, CSRF/Origin, logging redaction)
  spike:   22 passed (now uses its own database, AOS_SPIKE_DATABASE_URL)
  manual:  browser sign-in as Alice through the Vite proxy; JSON request logs show route
           templates only (no codes/state)

Checks not run:
  docker compose up (Docker not installed locally); images are built in CI instead.
  User interviews; blind human scoring (project lead).

Observed performance/cost: none measured; no provider cost incurred (fake providers only).

Known gaps:
  - Members can be added only after their first sign-in (no invitations).
  - Rate limiting arrives in M10.

Unresolved choices: none blocking M4.

Next bounded task: M4. Idempotent runs API, production worker (claim, heartbeat,
  fenced checkpointer, reconcile), fake-agent graph, persisted events + SSE replay,
  frontend shell (sign-in, workspace, brief form, run timeline), Playwright E2E.
```
