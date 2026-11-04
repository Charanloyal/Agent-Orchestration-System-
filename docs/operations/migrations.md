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
4. **Readiness checks the head.** `/readyz` returns 503 until the database is at the code's
   head revision; the worker waits for it.

## Apply

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic current          # where the database is
.\.venv\Scripts\python.exe -m alembic upgrade head     # local / compose
```

On Render, `alembic upgrade head` is the web service's pre-deploy command. If it fails, the
deploy fails and the previous version keeps serving.

## Roll back

Prefer rolling back **code** (redeploy the previous build). Schema downgrades are rarely
needed because migrations are additive. If one is needed:

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
