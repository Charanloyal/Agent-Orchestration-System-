# Database migrations and rollback

Alembic owns the application schema (`backend/migrations/versions`). LangGraph owns the `lg`
schema (checkpoints) and creates or upgrades it itself (`setup_checkpointer`).

## Rules

1. **Additive first.** New columns are nullable or have defaults; drop or rename only after
   no running code uses the old shape (expand → migrate → contract). The previous release
   must work on the new schema, so code rollbacks never need a schema downgrade.
2. **Every migration has a working `downgrade()`.** `test_downgrade_to_base_and_upgrade_again`
   runs every downgrade and upgrade on each test run.
3. **Models and migrations agree.** `test_models_match_migrations` fails on drift.
   Autogenerate (`alembic revision --autogenerate`) is a starting point. Triggers and
   functions (e.g. 0008) are written by hand.
4. **Declare compatibility** ([ADR 0020](../decisions/0020-schema-compatibility-window.md)).
   Every migration from 0009 on maintains the `schema_compatibility` table:
   - additive (the previous build still works on the new schema): insert the new revision,
     keep the other rows:
     `op.execute("INSERT INTO schema_compatibility (code_revision) VALUES ('0011')")`;
   - breaking for older code (drop, rename, NOT NULL without default, changed meaning): also
     delete the rows of the revisions it breaks, so those builds report not-ready instead of
     failing at runtime;
   - `downgrade()` deletes its own row.
5. **Readiness checks compatibility.** `/readyz` returns 503 (and the worker waits) unless
   the database is at the code's head, or at a newer revision that lists the code's head.
   It is never ready on an older schema. The messages say which case applies.

## Apply

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic current          # where the database is
.\.venv\Scripts\python.exe -m alembic upgrade head     # local / compose
```

On Render, `alembic upgrade head` is the web service's pre-deploy command (`render.yaml`) or
runs at start-up (`render.free.yaml`). If it fails, the deploy fails and the previous version
keeps serving.

## Roll back

Prefer rolling back **code** (redeploy the previous build). Within the compatibility window
the previous build is ready on the newer schema, so no schema change is needed; rehearsal 2
in [deploy-render.md](deploy-render.md#rehearsal-2-rollback-across-the-access-model-migration-0010)
exercises this. If a schema downgrade is really needed:

1. Take a backup (below) and stop the worker.
2. Rehearse on a copy: restore the backup into a scratch database, then run
   `alembic downgrade <revision>` against it and run the smoke checks.
3. Downgrade the real database, deploy the matching code, and start the worker.

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade -1   # one step; or a revision id such as 0007
```

## Back up and restore

`backend/scripts/backup_restore_drill.py` rehearses the full cycle on isolated databases, and
[load-and-recovery.md](load-and-recovery.md) records the measured drill. Manually:

```powershell
$bin = "$env:LOCALAPPDATA\Programs\postgresql-17\pgsql\bin"
& "$bin\pg_dump.exe" --format=custom --no-owner --file aos.dump "<source-url>"
& "$bin\pg_restore.exe" --no-owner --dbname "<empty-target-url>" aos.dump
```

On Render, managed Postgres has point-in-time recovery or daily backups, depending on plan
(see Render's Postgres docs). Use the dashboard's restore, which creates a new database, and
point `AOS_DATABASE_URL` at it after verification.

## Migration history

| Revision | Purpose |
| --- | --- |
| 0001 | Identity, workspaces, memberships, sessions, audit events |
| 0002 | Runs, jobs, events, plan/report versions, approvals, tool executions, sources, evidence, task results |
| 0003 | Uploads, chunks, full-text search |
| 0004 | Artifact generation provenance |
| 0005 | Budget reservations |
| 0006 | Review findings, report exports |
| 0007 | Rate-limit counters |
| 0008 | Append-only trigger on audit events |
| 0009 | `schema_compatibility` table: the window of code revisions that may run (ADR 0020) |
| 0010 | Access list, access requests, workspace invitations; current members copied onto the access list (ADR 0021). Additive: 0009 stays compatible |
