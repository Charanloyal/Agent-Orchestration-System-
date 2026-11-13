# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current state (2026-11-13 15:00): main = release/deploy-ready, pushed after this handoff.
  DEPLOYED at https://aos-web-8b4t.onrender.com (render.free.yaml; the owner deployed b53af5c
  or similar). The BLUEPRINTS CHANGED again (AOS_SECRETS_KEY generateValue; agents/search
  auto), so: Blueprint -> Manual sync, then Manual Deploy (migration 0011 runs on start).
  After deploying: Settings shows "AI engine and model provider" first; choose Google Gemini,
  paste a key, Test connection, Save; the pill turns "⚡ Live · gemini-2.5-flash" and new
  runs and Style studio rewrites use it (ADR 0029). Environment keys (GROQ_API_KEY etc.)
  still work for all workspaces (ADR 0028). Budget is USD 0 unless the owner approves: use a
  free-tier key with a provider-side limit. Gemini native adapter is unit-tested only; no live
  call was made from this laptop (no key).
  Owner override (2026-11-13): keys may be saved in the app (done, encrypted). Still declined:
  a "95% humanizer accuracy" figure and detector pass rates (the Style score is a published
  composite instead), a 5th "humanizer" agent inside the run workflow (the Style studio uses
  the same engine but is not a run step), one-click admin demo login, hard-coded admin emails.
  Not built: multi-document contradiction matrix.
  Hotfix (ADR 0030): the live Gemini run failed at planning with a bare "HTTP 400". Errors
  now carry Google's message (key masked), so Settings -> Test connection shows the real
  reason (most often "API key not valid": paste the key again). Non-key 400s retry once with
  plain settings; permanent model errors fall back to the deterministic agent, labelled in the
  timeline and on the plan/report. Retry the failed run after deploying.
  Earlier: smoke_prod.py 27/27 on 29449a6; check 12 (a) PASSED with AOS_TRUSTED_PROXY_HOPS=3
  (measured with /network-check; attempts 1-30 reach Google, 31-32 rate-limited despite
  forged headers). Records in docs/operations/rehearsals.md and records/. OPEN (owner, in the
  browser): checks 4-11 and 12 (b) of deploy-render.md, both rollback rehearsals, GitHub
  About settings, v1.0.0 tag. Live model: deploy-render.md section 6 (keys in Render's
  environment); budget still USD 0.
  Render does not auto-deploy: use Manual Deploy (code) or Blueprint Manual sync (settings).
  Free Postgres expires after about 30 days: upgrade or recreate before the viva.
  PUSH: `powershell -ExecutionPolicy Bypass -File .vscode\push.ps1` (classic token, repo +
  workflow). Tokens pasted in chat on 2026-11-11/12 must be deleted by the owner.
Commits after the deployment (newest first), all on main:
  (next) Style studio v2 (Markdown-aware, openers, measured rhythm, voices, rings, exports),
         obsidian theme + switch, sign-in portal, interactive Agents page, engine from
         provider keys (ADR 0028). Tests: backend 564 passed / 1 live deselected, ruff + mypy
         clean; Vitest 17 files / 95 tests; Playwright 14 passed (Chrome channel, CI=1).
  60adbbc ui: glass theme (contrast computed for overlapping aurora); deploy-render.md section 6
  26159a4 Style studio: measured metrics, fact-locked persona rewrite, no detector claims (0027)
  96df17e Agents page; sticky header never covers scrolled-to content
  4cdc937 trust three proxy hops (measured); dfc80c5 /network-check
  Tests at 60adbbc: backend pytest 543 passed / 1 live deselected, ruff + mypy clean;
  Vitest 16 files / 88 tests; Playwright 13 passed (Chrome channel, CI=1).
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

Architecture decisions: 0001-0028 (0004 superseded by 0018/0023; 0022 amended by 0026).
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
