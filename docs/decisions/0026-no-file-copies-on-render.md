# 0026: Keep no file copies on Render

- **Status:** Accepted
- **Date:** 2026-11-10
- **Requirements:** ADR 0019 (data lifecycle), ADR 0022 (ephemeral object store); findings
  F10 and G9; owner's decision "stored originals optional in prod, S3 only if chosen"
- **Amends:** ADR 0022, decision 3

## Context

The app writes two kinds of file copies to its object store: the original bytes of each
upload, and a Markdown copy of each export. Checking every code path:

- No route reads an upload original back. Search, evidence and citations use the extracted
  text and chunks in Postgres.
- No route reads a stored export back. Every download renders the report from Postgres, and
  the export record keeps the SHA-256 of exactly what was sent.

On Render the object store is the container's local disk, which is wiped on every deploy and
restart, and every service has its own. In the web + worker topology the worker's retention
sweep deletes database rows but cannot reach files on the web service's disk. So the copies
are written, never read, lost on the next deploy, and cannot be cleaned up by the sweep.
ADR 0022 documented this and let a re-upload restore a lost original.

## Decision

1. A setting, `AOS_STORE_FILES` (default `true`), decides whether copies are kept. With
   `false`, `get_object_store()` returns a `DiscardingObjectStore`: writes and deletes do
   nothing, nothing exists, and reading raises. Uploads, exports, run deletion and retention
   behave exactly as before otherwise.
2. All three Render blueprints set `AOS_STORE_FILES=false`; `scripts/check_blueprints.py`
   fails CI if one does not. Local development and Docker Compose keep copies (default).
3. The "restore a lost original on re-upload" path runs only when copies are kept.
4. An S3-compatible store remains the upgrade path if a later version needs to serve
   originals back (for example "download my file"). It would add a runtime dependency and an
   account, so it waits for the owner's decision.

## Alternatives considered

- **Keep copies and document the loss (ADR 0022 as it was).** Honest, but it keeps files that
  are never read and that the retention sweep cannot delete on the web disk.
- **A Render persistent disk.** Only for paid services, attaches to one service, and blocks
  zero-downtime deploys. It would fix the web disk but not the worker's access.
- **S3 now.** Correct and durable, but a new dependency and account for data nobody reads.

## Consequences

- Nothing a user sees changes: documents remain searchable and citable, and exports download
  as before. What a redeploy "loses" on Render is now nothing.
- Deleting an upload or a run, by a person or by retention, removes everything that exists:
  the database rows. Audit events still record the deletion.
- Tests: `test_without_stored_files_uploads_are_indexed_searched_and_deleted`,
  `test_exports_need_no_stored_copy`, `test_the_store_follows_the_setting`; CI asserts the
  production image keeps no copies with Render's settings.
