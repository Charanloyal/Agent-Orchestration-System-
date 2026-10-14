# Data model sketch

- **Status:** Sketch (Week 2). Week 3 turns it into SQLAlchemy models and Alembic migrations.
- **Already tested:** the tables marked *spike* exist in
  [spike/db.py](../../spikes/week2_persistence/spike/db.py) and are exercised by the spike
  tests. Everything else is a proposal.

## Principles

1. **Every tenant-owned row carries `workspace_id`.** Queries, workers, checkpoint access and
   retrieval filter by it. Consider PostgreSQL row-level security as defence in depth.
2. **Immutable artifacts.** Plan versions, report versions, approvals and evidence passages
   are insert-only. Edits create new versions.
3. **Deterministic uniqueness keys** make at-least-once execution idempotent (ADR 0008).
4. **Fencing:** rows written by workers record the `fencing_token` that wrote them.
5. **Dispatch vs progress:** `run_jobs` owns dispatch; LangGraph `checkpoints*` tables own graph
   progress (ADR 0007).
6. **Large content** (snapshots, uploads, exports) goes to object storage, referenced by key and
   SHA-256. Never authorize a download because a URL or key is known.

## Entities

| Entity | Key columns | Uniqueness / constraints | Notes | Spike |
| --- | --- | --- | --- | --- |
| `workspaces` | id, name | | | |
| `users` | id, oidc_subject, oidc_issuer | unique (issuer, subject) | No passwords stored | |
| `memberships` | workspace_id, user_id, role | PK (workspace_id, user_id); role ∈ analyst, reviewer, admin | | |
| `briefs` | id, workspace_id, created_by, body jsonb, idempotency_key, request_sha256 | unique (workspace_id, created_by, idempotency_key) | Same key + different hash → 409 (FR-02) | |
| `runs` | run_id, workspace_id, brief_id, state, deadline_at, parent_run_id | | `state` follows `ALLOWED_TRANSITIONS`; `parent_run_id` links retries | ✓ (subset) |
| `run_jobs` | run_id, state, waiting_for, resume_payload, lease_owner, lease_expires_at, fencing_token, attempts, available_at | check constraints tie lease and wait fields to state | Dispatch only | ✓ |
| `plan_versions` | run_id, version, digest, body | PK (run_id, version) | Immutable; server-assigned version | ✓ |
| `report_versions` | run_id, version, plan_version, digest, body | PK (run_id, version) | Immutable | ✓ |
| `approvals` | approval_id, run_id, artifact_kind, artifact_version, artifact_digest, decision, decided_by, decided_at | unique (run_id, artifact_kind, artifact_version) | Permission checked in the same transaction | ✓ |
| `sources` | source_id, workspace_id, run_id, kind, url, upload_id, title, retrieved_at, published_on, fetch_status, failure_reason, content_sha256, snapshot_key | unique (run_id, normalized_url, content_sha256) | Failed fetches kept, never citable | |
| `evidence_passages` | run_id, evidence_id, source_id, task_id, locator, text, text_sha256, fencing_token | PK (run_id, evidence_id) | Passage text capped (4000 chars); deterministic `evidence_id` | ✓ (`evidence`) |
| `claim_evidence` | run_id, report_version, claim_id, evidence_id | PK (all four) | FK to evidence in the same run (run-scoped citation) | |
| `review_findings` | run_id, report_version, review_round, finding_id, severity, category, body | PK (run_id, report_version, finding_id) | | |
| `tool_executions` | tool_execution_id, run_id, task_id, tool, status, fencing_token, started_at, finished_at, error_class | status ∈ started, succeeded, failed, abandoned | Recorded before the external call | ✓ |
| `usage_reservations` | id, run_id, workspace_id, estimated_cost, status, created_at | | Reserved transactionally before parallel calls | |
| `usage_reconciled` | reservation_id, provider, model_id, input_tokens, output_tokens, actual_cost, price_schedule_id | | Estimated vs actual | |
| `price_schedules` | id, provider, effective_from, body | | Prices used for estimates | |
| `run_events` | event_id (bigserial), run_id, event_type, payload, created_at | index (run_id, event_id) | Workspace-visible timeline; SSE cursor = event_id | ✓ |
| `audit_events` | id, workspace_id, actor, action, target, created_at | | Restricted operator log; no secrets or source text | |
| `uploads` | id, workspace_id, object_key, sha256, media_type, size, status | | Parser runs in isolation | |
| `exports` | id, run_id, report_version, approval_id, object_key, sha256, watermark | | Approved exports require an approval row | |
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` | Owned by langgraph-checkpoint-postgres | `thread_id` = run_id | Created by `PostgresSaver.setup()`; migrations are managed by the library, not Alembic | ✓ |

## Open questions for Week 3

- Should library-owned checkpoint tables live in a separate schema (for example `lg`), so
  Alembic autogenerate ignores them?
- Should `run_events` be partitioned or pruned under the retention policy (FR-12)?
- Use RLS policies or application-level scoping only? Decide after measuring complexity in
  Week 3.
