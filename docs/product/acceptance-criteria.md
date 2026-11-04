# Acceptance criteria matrix

Maps each PRD functional requirement (§2.7) and proposed release gate (§2.8) to testable
criteria and the evidence that verifies them. Updated at M12 (2026-11-03).

**Status key:**
- **Verified**: automated tests in `backend/tests` or `frontend/e2e` pass in CI.
- **Partly**: part of the criterion is verified; the rest is stated.
- **Open**: not yet met; the reason is given.

| ID | Requirement | Testable criteria | Evidence | Status |
| --- | --- | --- | --- | --- |
| FR-01 | Access and isolation | Every run, event, source, checkpoint, report, approval and download authorized server-side by workspace; guessed IDs and cross-workspace search fail | `test_authz.py` (matrix generated from every route: 401 unauthenticated, 404 other workspace, CSRF/Origin on unsafe methods); `test_search_never_crosses_workspaces`; E2E cross-workspace 404 | Verified |
| FR-02 | Brief creation | Invalid limits rejected; same idempotency key and body → same run; same key, different body → 409 | `test_contract_models.py`; `test_idempotent_creation` | Verified |
| FR-03 | Planning | Cycles, unknown references, unsupported tools and over-limit plans rejected; planner cannot widen the allowlist | `test_contract_plan.py`; `test_planner_cannot_expand_tool_allowlist` | Verified |
| FR-04 | Human approvals | Decisions bind to version and digest; edits create a new version needing approval; permission checked at decision time; rejected plan → new version; rejected report not exportable as approved | `test_stale_and_wrong_kind_decisions_rejected`; `test_plan_rejection_creates_new_version`; `test_report_rejection_needs_attention`; `test_rejected_report_exports_only_as_draft`; `test_role_separation` | Verified |
| FR-05 | Research and retrieval | Stable source ID, URL or upload ref, retrieval time, hash, title, locator; publication date separate; failed fetches recorded, never presented as read; SSRF blocked | `test_research_sources.py`; `test_fetcher.py` (private/metadata IPs, DNS rebinding, redirects, size, timeouts) | Verified |
| FR-06 | Drafting | Verifiable claims cite run evidence; claim kinds distinguished; missing evidence stated | `test_review_export.py` (writer validation, repair); claim contract tests | Verified (deterministic); semantic quality needs the live evaluation |
| FR-07 | Review and citation validation | Unknown or unauthorized evidence IDs rejected; support checked; at most 2 rounds → NEEDS_ATTENTION | `test_planted_unsupported_claim_is_caught_revised_and_persisted`; `test_unresolved_findings_after_two_rounds_need_attention`; `test_review_routing_is_bounded` | Verified (deterministic + scripted model) |
| FR-08 | Durable execution | Worker crashes at any step do not lose or duplicate committed work; stale workers cannot write | 10-point OS-level crash suite and stale-owner fencing in `test_worker_recovery.py` | Verified |
| FR-09 | Resource controls | Spend reserved before concurrent calls, reconciled after; scheduling stops when funds run out; tool-call and parallelism limits hold | `test_research_budgets.py` (10-thread reservation race, tool limit under parallelism, exhaustion) | Verified |
| FR-10 | Progress and cancellation | SSE replay from cursor; cancellation stops new work; requested vs completed cancellation visible | `test_sse_replays_and_resumes_after_last_event_id`; `test_cancel_retry.py`; E2E cancel | Verified |
| FR-11 | Reporting and audit | Immutable versions; approved export generated server-side from the approved version and digest; drafts watermarked; logs and audit carry no secrets or source text | `test_review_export.py`; `test_logging.py`; `test_observability.py` (trace redaction); `test_audit_log_is_admin_only_and_content_free` | Verified |
| FR-12 | Retention and deletion | Documented policy; deletion removes active copies and blocks access; backup expiry documented | `test_admin_deletes_a_finished_run_completely…`; `test_retention_sweep…`; `test_audit_log_is_append_only…`; [data-retention.md](../operations/data-retention.md) | Verified |

## Release gates (proposed targets)

| Gate | Target | Evidence | Status |
| --- | --- | --- | --- |
| API p95 | < 500 ms for metadata endpoints at 20 concurrent clients | Load test ([load-and-recovery.md](../operations/load-and-recovery.md), M14) | Open (M14) |
| Throughput | 5 concurrent end-to-end runs without corruption, budget races or leakage | Load test (fake providers, M14) | Open (M14) |
| Recovery | 10/10 crash scenarios preserve committed results with no duplicates | `test_worker_recovery.py` | Verified |
| Citation integrity | 100% of citation IDs resolve to run evidence | `validate_citations` on every draft; evaluation citation validity 100% (fake agents, 90 runs) | Verified for the harness; live run pending |
| Evidence support | ≥ 90% of sampled claims supported, with denominator and CI | Blind human sample (`evaluation.blind`) | **Open**: needs a live run and two human scorers |
| Completion | ≥ 90% of answerable briefs produce a reviewable draft | Fake agents: 18/18 answerable dev runs per system (harness validation only) | **Open** for real models |
| Control tests | 0 unauthorized tool calls or cross-workspace disclosures | Authz matrix; injected-URL fixtures (never fetched); SSRF suite | Verified (automated); no external penetration test |
| Operability | Backup restore, rollback, readiness and provider-failure alerts tested | Readiness tests; restore drill (M14); rollback documented, not rehearsed on Render | Partly |