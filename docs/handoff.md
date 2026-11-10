# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current state (2026-11-10): Phase A (read-only audit) done; Phase B in progress. Branch
  release/deploy-ready holds all work since M16. GitHub has it up to 3aff454, whose CI was red
  only in e2e (fixed by 754c7af). The newer commits below are committed locally and wait for the
  owner's push (an agent shell cannot authenticate to GitHub on this machine). No pull request
  yet; nothing is deployed.

Commits after M16 (d8de167), in order:
  45782cd sign-in hardening, schema compatibility window (migration 0009), deploy tooling
  02074c7 access model (migration 0010): platform admins, signup modes, invitations, requests
  336701f UI: onboarding, workspace settings, access administration, accessibility
  8bd59ea docs and close-out (ADRs 0020-0022, deploy guide, threat model, research prep)
  b73469f config: the worker and migrations start without web-only settings
  3aff454 deploy: hybrid blueprint in Singapore; CI proves every topology and the older build
  ---- on GitHub up to here ----
  55d2d6e auth: trust only provider-verified email addresses (G2, ADR 0024)
  754c7af web: keep access-decision notices after the request row closes (the CI e2e failure)
  18babd1 e2e: no retries for stateful access journeys; keep worker output
  (this handoff)

Architecture decisions: 0001-0024 (0023 deploy topologies and CI proof; 0024 verified email only).
Database migrations: 0001 ... 0010 (0009 stays compatible with 0010; ADR 0020).

Tests actually run (2026-11-10, Windows 11, Python 3.14.7, PostgreSQL 17.11, Node 24.21):
  backend: ruff + format clean, mypy clean (101 files), pytest 477 passed / 1 live deselected;
  frontend: typecheck clean, Vitest 14 files / 81 tests, production build OK;
  Playwright with CI=1 (Edge channel; the bundled Chromium download is blocked by the local
  proxy): 12 passed, no retries.
  M16 baseline for comparison: pytest 398, Vitest 35, Playwright 6.

Checks not run locally: Docker image builds, Render schema validation and the per-topology
  smoke tests (CI deploy-image job only; green on 3aff454).

Open findings (Phase C): G3 forwarded-for trust, G4 role health checks, G5 security headers and
  __Host- cookie, G6 pool sizes, G7 retention for the viva (owner: RUN_RETENTION_DAYS=0),
  G8 commit in /healthz and the UI footer, G9 storage and retention across disks; plus F4
  RENDER_EXTERNAL_URL fallback, F5 exact discovery issuer, F9 corpus fail-fast, F13 supersede
  ADR 0004 and the brief's UNDECIDED rows. G10 is Phase F.

Blocked by owner (each has a written procedure):
  1. Push release/deploy-ready, open the PR to main, merge once CI is green.
  2. Render deployment with Google sign-in: docs/operations/deploy-render.md (Phase D).
  3. Rollback rehearsals 1 and 2: docs/operations/rehearsals.md.
  4. Live evaluation: budget approval (LIVE_BUDGET_USD is 0), then the evaluation plan.
  5. Blind scoring by two scorers; interviews, usability study, NVDA session.

Before pushing: push only refs/heads/release/deploy-ready, never refs/agents/*. Merging to main
  deploys once a Render Blueprint with autoDeployTrigger: checksPass exists. The release tag is
  v1.0.0, created only after the owner approves (Phase F).
```
