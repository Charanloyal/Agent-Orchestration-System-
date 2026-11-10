# 0020: A schema compatibility window, so rollbacks work across migrations

- **Status:** Accepted
- **Date:** 2026-11-06
- **Requirements:** PRD operability (deploy and roll back safely); ADR 0018 (Render
  deployment); finding B1 (rollback blocked by an exact-revision readiness check)

## Context

Readiness (`/readyz`) and worker start-up accepted the database only when its Alembic
revision *equalled* the code's head. Render runs `alembic upgrade head` as a pre-deploy step,
then switches traffic. If the new build then misbehaves, the documented rollback ("redeploy
the previous build; migrations are additive") could not work: the previous build would see a
newer revision, report not ready, and Render would keep it out of service. The worker would
wait forever. Rolling back would have required a schema downgrade under pressure, which is
exactly what the additive-migration rule was meant to avoid.

## Decision

1. **A `schema_compatibility` table** (migration 0009) lists the code revisions that may run
   against the database. It is written only by migrations.
2. **Rule for every later migration** (enforced by review and documented in
   [migrations.md](../operations/migrations.md)):
   - *additive* changes (new tables, nullable columns, new indexes, backfills that old code
     ignores) insert the new revision and keep the existing rows;
   - *breaking* changes for older code (drops, renames, new NOT NULL columns without defaults,
     changed meaning) delete the rows of the code revisions they break;
   - every downgrade deletes its own row.
3. **Readiness and worker start-up** (`app/db/schema_state.py`) accept the database when:
   - it is exactly at the code's head; or
   - it is at a revision this code does not know (newer), *and* the table lists the code's
     head as compatible.
   A database at an older revision that the code knows is never accepted ("run alembic
   upgrade head"). The two refusals have distinct messages.
4. **`GET /version`** reports the serving build (`RENDER_GIT_COMMIT`) and its migration head,
   so a rollback can be verified from outside (`scripts/smoke_prod.py --expect-commit`).

## Consequences

- The build before 0010 (head 0009) stays ready on a 0010 database. Rehearsal 2 in
  [deploy-render.md](../operations/deploy-render.md) exercises exactly this.
- Builds older than 0009 do not know the table and still require an exact match. The window
  starts at 0009, so the first deployment of the access model must follow a deployment of
  0009 for its rollback to be possible.
- A wrong row (a breaking migration that forgets to delete a compatibility row) would let an
  incompatible build report ready. Breaking migrations are reviewed against this rule, and
  tests cover both the accepted and the refused case.
- The backup/restore drill still checks for an exact head, because a restored database must
  match the build that restores it.
