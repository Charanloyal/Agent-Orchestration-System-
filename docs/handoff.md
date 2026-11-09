# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current state: v1.0 release candidate, committed locally on main and NOT pushed. Phases 1-4
  and the repository side of 5, 7, 8 and 9 are done. The tag v1.0.0-pilot waits for the
  owner's approval. Nothing is in progress.

Commits (local, in order; see `git log --oneline`):
  1. Sign-in hardening, schema compatibility window and deploy tooling (phases 1-2):
     migration 0009 (schema compatibility window), /version, scripts/smoke_prod.py,
     render.free.yaml + app/serve.py, login-binding cookie, named sign-in errors,
     /auth/config, Google issuer forms, favicon, storage restore on re-upload. This is the
     "0009 build" for rollback rehearsal 2; on its own it passes ruff, mypy and pytest
     (420 passed).
  2. Access model (phase 3): migration 0010, platform admins, signup modes, access list,
     access requests, invitations, admin routes, production rules (pytest 463 passed).
  3. UI (phase 4): onboarding, workspace settings, access administration, request-access
     form, notifications, 401/403 handling, dark mode, 360 px, axe/keyboard E2E.
  4. Documentation and close-out (phases 5-9): ADRs 0020-0022, deploy guide with Google
     OAuth and two rehearsals, records page, threat model T18-T22, runbook, retention,
     user guide with 17 re-captured screenshots, research prep, CHANGELOG, this handoff.

Architecture decisions accepted:
  0001-0019 as before; 0020 schema compatibility window; 0021 access model; 0022 deployment
  variants and the ephemeral object store.

Database migrations:
  0001 ... 0010. 0009 adds schema_compatibility ('0009'); 0010 adds access_list_entries,
  access_requests, workspace_invitations, copies current members onto the access list, and
  adds '0010' (0009 stays compatible).

Tests actually run (2026-11-09, Windows 11, Python 3.14.7, PostgreSQL 17.11, Node 24.21):
  backend: ruff + format clean, mypy --strict clean (101 files), pytest 463 passed /
  1 live test deselected (204 s, database tests ran);
  frontend: typecheck clean, vitest 14 files / 79 tests passed, production build OK;
  Playwright (Edge, real API + worker + dev IdP + Postgres): 13 passed, including axe-core
  WCAG 2.2 A/AA on every page in light and dark mode, 360 px layouts, keyboard, the
  invitation, access-request and session-expiry journeys, and the screenshot capture.

Checks not run locally:
  Docker image builds and the deploy-image smoke test (no Docker here; CI runs both, now
  including smoke_prod.py and the single-service variant). Render schema validation (CI).
  Everything that needs the owner (below).

Blocked by owner (each has a written procedure):
  1. Render deployment with Google sign-in: docs/operations/deploy-render.md. Deploy the
     "0009 build" (commit 1) first, then main, so rehearsal 2 is possible.
  2. Rollback rehearsals 1 and 2, recorded in docs/operations/rehearsals.md.
  3. Live evaluation (LIVE_EVAL not approved): key in backend/.env, written budget approval
     of at most USD 10, then docs/evaluation/evaluation-plan.md "Live run checklist".
  4. Blind human scoring with two scorers.
  5. Interviews, usability study, NVDA session: docs/product/interview-guide.md,
     usability-study.md, accessibility-checklist.md.
  After 3-4, update report sections 13.5, 14 and 17 with measured results only.

Before pushing:
  Pushing main triggers CI and, once a Render Blueprint with autoDeployTrigger: checksPass
  exists, a deploy. Never push refs/agents/* (they contain a corporate email). Tag
  v1.0.0-pilot only after approval.
```