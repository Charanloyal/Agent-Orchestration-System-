# Session handoff

Uses the template from the context prompt (Â§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current state (2026-11-12 01:30): main on GitHub = 44c3887 (PR #1 merged + 6 fix commits,
  pushed with .vscode/push.ps1). CI on 44c3887: backend, frontend, containers, spike and
  deploy-image (every Render topology, health checks, older-build compatibility) GREEN; e2e
  had one failing test (Documents too wide at 360 px on Linux fonts). Fixed locally in
  bd423dd (file input can shrink; widths also checked at 320 px); waiting for the owner's
  push. Nothing is deployed yet.
  PUSH: `powershell -ExecutionPolicy Bypass -File .vscode\push.ps1` (classic token with repo
  + workflow; Git's sh.exe is broken on this laptop, so normal sign-in cannot work).
Commits after M16 (d8de167), in order:
  45782cd sign-in hardening, schema compatibility window (migration 0009), deploy tooling
  02074c7 access model (migration 0010): platform admins, signup modes, invitations, requests
  336701f UI: onboarding, workspace settings, access administration, accessibility
  8bd59ea docs and close-out (ADRs 0020-0022, deploy guide, threat model, research prep)
  b73469f config: the worker and migrations start without web-only settings
  3aff454 deploy: hybrid blueprint in Singapore; CI proves every topology and the older build
  ---- on GitHub up to here ----
  55d2d6e G2  auth: trust only provider-verified email addresses (ADR 0024)
  754c7af     web: access-decision notices survive the request row closing (CI e2e failure)
  18babd1     e2e: no retries for stateful access journeys; keep worker output
  a7e6489     docs: phase B handoff
  103f1a9 G3  rate-limit keys use the trusted proxy's client address (ADR 0025)
  ab28673 G7  runs and uploads kept until deleted on Render (retention 0)
  bcabd90 G5  production HSTS, COOP, Permissions-Policy; __Host-/__Secure- cookies
  37d687c G8  /healthz and the page footer name the version and commit
  0e1d534 G6  pool sizes are settings; connection budget 83 / 43 / 43 of Render's 100
  99affb6 G4  one health check for web, worker and the single process (app.healthcheck)
  5d117ff     client-address tests independent of rate-limit window timing
  0f678b0 G9  keep no file copies on Render (AOS_STORE_FILES=false, ADR 0026)
  a28d53f F4  RENDER_EXTERNAL_URL is the public URL unless AOS_PUBLIC_URL is set
  7c8f9fd F5  ID tokens checked against the exact issuer from discovery (Auth0)
  1552a84 F9  a missing corpus stops start-up instead of finding nothing
  3d9ddba F13 ADR 0004 superseded; project brief and risk register current
  (this handoff)

Architecture decisions: 0001-0026 (0004 superseded by 0018/0023; 0022 amended by 0026).
Database migrations: 0001 ... 0010 (0009 stays compatible with 0010; ADR 0020). Phase C added
  none.

Tests actually run (2026-11-10, Windows 11, Python 3.14.7, PostgreSQL 17.11, Node 24.21):
  backend: ruff + format clean, mypy clean (103 files), pytest 515 passed / 1 live deselected;
  scripts/check_blueprints.py: all three blueprints pass;
  frontend: typecheck clean, Vitest 14 files / 83 tests, production build OK;
  Playwright with CI=1 (Edge channel; the bundled Chromium download is blocked by the local
  proxy): 12 passed, no retries.
  Baselines: M16 pytest 398 / Vitest 35 / Playwright 6; 9 Nov 463 / 79 / 13.

Checks not run locally (CI deploy-image job only, first run after the push): Docker image
  build, Render schema validation, per-topology smoke tests, the new health-check assertions
  (web, worker, single), RENDER_EXTERNAL_URL start-up, AOS_STORE_FILES probe.

Findings: F1-F13 and G2-G10 closed on the branch (G10: README, LICENSE, release notes; the
  GitHub About settings are owner steps in docs/github-settings.md). Open: G1 (push, PR, green
  CI including the unexplained e2e failure, merge) and F14 (live run; budget USD 0). Known
  flaky pattern, not changed: test_observability's login rate-limit test counts within one
  5-minute window.
Next steps in order: owner pushes and opens the PR -> agent reads the e2e annotations and fixes
  until green -> owner merges with a merge commit -> Phase D guided (Google OAuth client,
  Blueprint render.hybrid.yaml, smoke_prod + check 12, verification table, rehearsals) ->
  hosted PENDING lines filled from pasted evidence -> tag v1.0.0 after approval.

Blocked by owner (each has a written procedure):
  1. Push release/deploy-ready, open the PR to main, merge once CI is green (Phase B).
  2. Render deployment with Google sign-in: docs/operations/deploy-render.md (Phase D),
     including check 12 (trusted proxy hops) and the rollback rehearsals.
  3. Live evaluation: budget approval (LIVE_BUDGET_USD is 0), then the evaluation plan.
  4. Blind scoring by two scorers; interviews, usability study, NVDA session.

Before pushing: push only refs/heads/release/deploy-ready, never refs/agents/*. Merging to main
  deploys once a Render Blueprint with autoDeployTrigger: checksPass exists. Merge with a merge
  commit (not squash) so rollback rehearsal 2 can deploy the 0009 build. The release tag is
  v1.0.0, created only after the owner approves (Phase F).
```
