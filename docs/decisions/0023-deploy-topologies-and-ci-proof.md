# 0023: Deployment topologies, role-specific settings and deploy proof in CI

- **Status:** Accepted
- **Date:** 2026-11-10
- **Requirements:** ADR 0018 (production image), ADR 0020 (schema compatibility window),
  ADR 0022 (deployment variants); finding G1; the owner's decisions RENDER_TOPOLOGY = hybrid
  and RENDER_REGION = singapore

## Context

Render deploys from GitHub, and GitHub Actions is the only place the production image is
built and started. Before this decision CI proved one blueprint shape (web and worker) plus
the single-service command, but not that each blueprint actually starts the image that way.
The worker validated the same production settings as the web service, so it needed sign-in
secrets it never uses. The older-build guarantee of ADR 0020 was proven only by a simulated
test.

The owner chose a hybrid topology: one free web service running API and worker, with a paid
Postgres that does not expire before the viva.

## Decision

1. **Three blueprints, one region.** `render.yaml` (web, worker, pre-deploy migration, paid),
   `render.hybrid.yaml` (free web service running `python -m app.serve --migrate
   --with-worker`, Postgres `basic-256mb`), `render.free.yaml` (as hybrid, free Postgres).
   All use `singapore`, because Render cannot move a service or database after creation.
2. **Role-specific production settings.** `Settings` refuses only what is unsafe for every
   process: no database URL, test-only fault injection, open signup with model agents. The web
   app checks the settings only it uses (`Settings.web_problems()`: sign-in issuer and client,
   secure cookies, https public URL, platform admins) when it is created. The worker and the
   pre-deploy migration start with database settings alone; `render.yaml` gives the worker no
   sign-in variables.
3. **CI proves deployability** (`deploy-image`, on pull requests and pushes to `main` and
   `release/**`):
   - every `render*.yaml` passes Render's published schema, and `scripts/check_blueprints.py`
     checks that each one starts the image the way the job does (web with the image command
     and the pre-deploy migration plus a worker running the runner, or one service running
     `app.serve`), with one region per blueprint and no web settings on a worker;
   - the image is started per topology with production settings against Postgres and passes
     `scripts/smoke_prod.py`; the worker starts with database settings only; the single
     process migrates a fresh database on start;
   - **older build:** the commit just before the newest migration is built and started on the
     new schema. It must be ready, pass the smoke test and start its worker.

## Consequences

- A blueprint that drifts from what CI starts fails CI, both in the backend tests
  (`test_blueprints.py`) and in `deploy-image`.
- The older-build check builds a second image, so `deploy-image` takes longer. It needs the
  full history, so the release must be merged with a merge commit, not squashed: a squash
  would put migrations 0009 and 0010 in one commit and leave no 0009 build to test or to roll
  back to.
- Builds before 0009 cannot pass the check; they predate the compatibility window. The check
  always uses the build just before the newest migration, which is 0009 or later.
- The 0009 build itself still validates web settings in its worker. Rolling the separate
  worker of `render.yaml` back to it needs those variables again (see deploy-render.md).
