# Data retention, deletion and public-demo data policy

See [ADR 0019](../decisions/0019-data-lifecycle-audit.md) for the design.

## What is stored

| Data | Where | Contains |
| --- | --- | --- |
| Briefs, plans, reports, review findings | Postgres | Text you and the agents wrote |
| Evidence passages and sources | Postgres | Excerpts of fetched pages or uploaded documents, with URLs and dates |
| Uploads | Postgres (extracted text) + object store (original file) | Your documents |
| Exports | Object store (Markdown copy) + Postgres (record and digest) | The report as exported |
| Workflow checkpoints | Postgres schema `lg` | Workflow state per run |
| Timeline events, cost ledger | Postgres | Structured summaries; no prompts or source text |
| Audit events | Postgres | Who did what, when, to which id; no content |
| Logs, traces, metrics | stdout / tracing backend | Ids, counts and timings; secrets redacted; no content |

## Retention

| Data | Default (local) | Render blueprint | Mechanism |
| --- | --- | --- | --- |
| Finished runs and everything derived from them | Kept | 30 days after the last update | Worker retention sweep (`AOS_RETENTION_RUN_DAYS`) |
| Uploads | Kept | 30 days after upload | Worker retention sweep (`AOS_RETENTION_UPLOAD_DAYS`) |
| Unfinished runs | Never swept | Never swept | Cancel first, then they age out |
| Audit events | Kept | Kept | Append-only; removal only by a database owner |
| Database backups | Operator's choice | Render plan's backup window | Deleted data persists in backups until they expire |

## Deletion

- **A run:** a workspace admin deletes a finished run (`DELETE /api/v1/runs/{id}`, or **Delete
  run** in the UI). This removes it, its derived data, its checkpoints and its export files.
- **An upload:** the uploader or an admin deletes it on the Documents page. Passages already
  copied into runs stay with those runs until the runs are deleted.
- **Not possible:** audit events cannot be deleted through the application.

## Public-demo data policy

The hosted demo is a *controlled pilot*:

- Sign-in is limited to an allowlist.
- It runs **deterministic fake agents** unless an approved budget enables a model.

Rules for users:

1. **Use only public or synthetic material.** Do not upload confidential, personal or
   employer documents. With a model enabled, text is sent to the model provider
   ([ADR 0002](../decisions/0002-model-provider.md)).
2. **Expect data to be deleted after 30 days** (retention sweep). Uploaded originals can
   also disappear on redeploy (ephemeral filesystem); extracted text remains until retention.
3. **Reports are research aids, not advice.** A human approval records that a reviewer
   checked the cited evidence; it does not certify the content.
4. **Ask an admin to remove your runs or documents at any time.** Deletion is immediate in
   the database; backups age out on the platform's schedule.
