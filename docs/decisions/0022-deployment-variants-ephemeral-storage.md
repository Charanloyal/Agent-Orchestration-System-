# 0022: Deployment variants and the ephemeral object store

- **Status:** Accepted
- **Date:** 2026-11-06
- **Requirements:** ADR 0004 (deployment target), ADR 0018 (production image); finding F10
  (storage behaviour on Render)

## Context

`render.yaml` describes the intended deployment: one web service, one background worker, a
pre-deploy migration and a paid Postgres. Background workers and pre-deploy commands need paid
instance types. A portfolio or evaluation deployment may have to run on the free plan.

Separately, the object store is the container's local disk, and on Render that disk is
ephemeral: it is wiped on every deploy and restart. We had to answer what is actually lost.
- Every read path (reports, exports, evidence, search) uses Postgres. Exports are regenerated
  from the stored report versions; nothing reads a stored export back.
- What is lost is an uploaded *original* file. Its extracted text and chunks are in Postgres,
  so search and citations keep working. Only the original bytes are gone.
- Re-uploading the same file used to return the existing record without restoring the
  original.

## Decision

1. **Two blueprints.**
   - `render.yaml` (recommended): web + worker + pre-deploy migration, paid plans.
   - `render.free.yaml`: one free web service running `python -m app.serve --migrate
     --with-worker`. It migrates on start, runs the worker as a supervised child process
     (restarted if it exits), and serves with uvicorn. The free Postgres plan is time-limited
     by Render, so the documentation tells the owner to check the current limits.
   CI validates both files against Render's published schema.
2. **Migrate-on-start is safe** because migrations are additive and the previous build stays
   compatible (ADR 0020). A failed migration stops the new instance from starting, and the
   old one keeps serving.
3. **The ephemeral disk is documented, not hidden.** The user guide, the data-retention page
   and the deploy guide say what survives a redeploy. Uploading the same file again restores
   a missing original, with a log line. A persistent disk or an S3-compatible store is the
   documented upgrade (the `ObjectStore` protocol now includes `exists`).

## Consequences

- On the free plan, the service sleeps when idle. The first request after a pause is slow,
  and a run waiting in the queue is picked up only once the service is awake. This is
  acceptable for a demo, not for a pilot.
- One process holds both the API and the worker, so a crash loop in one affects the other.
  The supervisor restarts the worker; uvicorn's own failure restarts the container.
- Re-uploading restores originals only when someone does it. Nothing tries to repair
  originals in bulk.
