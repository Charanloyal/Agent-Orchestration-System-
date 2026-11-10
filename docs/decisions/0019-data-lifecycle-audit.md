# 0019: Data lifecycle: deletion, retention and an append-only audit log

- **Status:** Accepted
- **Date:** 2026-11-03
- **Requirements:** PRD week 13 (retention, deletion, auditability); threat model T3, T12;
  ADR 0009 (workspace authorization)

## Context

Runs accumulate briefs, evidence copied from sources, reports, checkpoints and export files.
Users must be able to remove them; the pilot must not keep data forever; and the security log
must remain trustworthy when data is deleted.

## Decisions

1. **User-requested run deletion:** `DELETE /api/v1/runs/{id}`, workspace admins only
   (`data.delete`).
   - Only finished runs can be deleted, and never while a worker holds the lease (409 asks
     you to cancel first).
   - One transaction deletes the brief; `ON DELETE CASCADE` removes the run, job, events,
     plan and report versions, approvals, sources, evidence, task results, tool executions,
     budget reservations, review findings and export records.
   - The run's LangGraph checkpoints are removed in the same transaction.
   - Exported files are deleted from the object store *after* the commit. A failure leaves a
     logged orphan file, never a dangling database reference.
   - Upload deletion (uploader or admin) uses the same commit-then-remove-file order.
2. **Retention sweep** in worker maintenance, configured with `AOS_RETENTION_RUN_DAYS` and
   `AOS_RETENTION_UPLOAD_DAYS` (0 = off, the local default).
   - Finished runs are aged by their last update and uploads by creation time. Unfinished
     runs are never swept.
   - Batches are small, and locks use `SKIP LOCKED`, so the sweep never blocks a worker or a
     user.
   - The Render blueprints set both to 0 (keep until deleted), so the demo survives until the
     viva; `scripts/check_blueprints.py` enforces it. (Until v1.0 they set 30 days.)
3. **Audit events are append-only**, enforced by a database trigger (migration 0008).
   - DELETE and content updates are refused. The only update allowed is the foreign-key
     `SET NULL` when a user or workspace is deleted, so the record survives with its action,
     target id, details and time.
   - Deletions and retention sweeps write their own audit events with ids and counts, never
     content.
   - Admins read their workspace's events at `GET /api/v1/workspaces/{id}/audit` (new
     permission `audit.read`). Events from other workspaces are never returned.
4. **What is deliberately kept:**
   - Audit events.
   - Evidence passages copied into a run stay with that run when the original upload is
     deleted. They are part of the record the report was approved on, and go when the run
     goes.

## Consequences and limitations

- A database superuser can disable the trigger. Append-only protects against the
  application and its operators, not against a compromised database owner. A hash chain or
  external log shipping would be the next step.
- There is no workspace or account self-deletion endpoint yet; an operator removes them with
  SQL. Audit rows survive with nulled actor or workspace.
- Backups taken before a deletion still contain the deleted data until they age out. The
  backup retention period is part of the operator's policy
  ([data-retention.md](../operations/data-retention.md)).
