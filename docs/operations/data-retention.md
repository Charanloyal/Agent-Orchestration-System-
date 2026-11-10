# Data retention, deletion and public-demo data policy

See [ADR 0019](../decisions/0019-data-lifecycle-audit.md) for the design, and
[ADR 0021](../decisions/0021-access-model.md) / [ADR 0022](../decisions/0022-deployment-variants-ephemeral-storage.md)
for access data and storage.

## What is stored

| Data | Where | Contains |
| --- | --- | --- |
| Briefs, plans, reports, review findings | Postgres | Text you and the agents wrote |
| Evidence passages and sources | Postgres | Excerpts of fetched pages or uploaded documents, with URLs and dates |
| Uploads | Postgres (extracted text) + object store (original file) | Your documents |
| Exports | Object store (Markdown copy) + Postgres (record and digest) | The report as exported |
| Workflow checkpoints | Postgres schema `lg` | Workflow state per run |
| Timeline events, cost ledger | Postgres | Structured summaries; no prompts or source text |
| Audit events | Postgres | Who did what, when, to which id; no content and no requester emails |
| Access list | Postgres | Email, how it was added, optional note, who added it |
| Access requests | Postgres | Email, name, optional message, decision |
| Workspace invitations | Postgres | Email, role, inviter, expiry, outcome |
| Logs, traces, metrics | stdout / tracing backend | Ids, counts and timings; secrets redacted; no content |

## Retention

The Render blueprints keep finished runs and uploads until someone deletes them, so the demo
runs created at deploy time are still there at the viva. To clean up automatically, set
`AOS_RETENTION_RUN_DAYS` / `AOS_RETENTION_UPLOAD_DAYS` to a number of days in the blueprint;
finished runs are then aged by their last update and uploads by creation time.

| Data | Default (local) | Render blueprint | Mechanism |
| --- | --- | --- | --- |
| Finished runs and everything derived from them | Kept | Kept until deleted (`"0"`) | Worker retention sweep (`AOS_RETENTION_RUN_DAYS`; 0 = off) |
| Uploads | Kept | Kept until deleted (`"0"`) | Worker retention sweep (`AOS_RETENTION_UPLOAD_DAYS`; 0 = off) |
| Unfinished runs | Never swept | Never swept | Cancel first, then they age out |
| Decided access requests | 90 days after the decision | 90 days | Worker retention sweep (`AOS_RETENTION_ACCESS_REQUEST_DAYS`); pending requests are kept until decided |
| Access list entries | Until a platform admin removes them | Same | Removal also revokes the person's sessions |
| Invitations | Kept as a record (accepted, revoked or expired) | Same | Removed with their workspace |
| Stored originals and export copies on Render | Until the next restart or deploy | Same | Ephemeral disk; re-uploading restores an original |
| Audit events | Kept | Kept | Append-only; removal only by a database owner |
| Database backups | Operator's choice | Render plan's backup window | Deleted data persists in backups until they expire |

## Deletion

- **A run:** a workspace admin deletes a finished run (`DELETE /api/v1/runs/{id}`, or **Delete
  run** in the UI). This removes it, its derived data, its checkpoints and its export files.
- **An upload:** the uploader or an admin deletes it on the Documents page. Passages already
  copied into runs stay with those runs until the runs are deleted.
- **Access:** a platform admin removes an email from the access list on the Access page; a
  denied request is deleted with the others after 90 days. To have a request deleted sooner,
  ask a platform admin.
- **Not possible:** audit events cannot be deleted through the application.

## Public-demo data policy

The hosted demo is a *controlled pilot*:

- Sign-in is limited to platform admins, the access list and invited people; others can
  request access.
- It runs **deterministic fake agents** unless an approved budget enables a model.

Rules for users:

1. **Use only public or synthetic material.** Do not upload confidential, personal or
   employer documents. With a model enabled, text is sent to the model provider
   ([ADR 0002](../decisions/0002-model-provider.md)).
2. **Do not rely on the demo as an archive.** Runs and uploads are kept until an admin deletes
   them, but the hosted demo may be reset after the project ends.
3. **Reports are research aids, not advice.** A human approval records that a reviewer
   checked the cited evidence; it does not certify the content.
4. **Ask an admin to remove your runs or documents at any time.** Deletion is immediate in
   the database; backups age out on the platform's schedule.
