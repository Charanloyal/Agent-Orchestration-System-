# Acceptance criteria matrix

This maps each PRD functional requirement (§2.7) and proposed release gate (§2.8) to testable
criteria, the planned tests and the milestone that delivers them.

**Status key:**
- **Contract**: enforced by a typed contract with passing unit tests ([backend/tests](../../backend/tests)).
- **Spike**: shown by a Week-2 spike test against PostgreSQL ([spikes/week2_persistence](../../spikes/week2_persistence)).
  Spike code is throwaway; production tests are still required.
- **Planned**: not implemented.

| ID | Requirement | Testable criteria | Planned test(s) | Milestone | Status |
| --- | --- | --- | --- | --- | --- |
| FR-01 | Access and isolation | Every run, event, source, checkpoint, report, approval and download is authorized server-side by workspace; guessed IDs and cross-workspace evidence search fail | API authz matrix over every route × role × foreign-workspace ID; worker and retrieval scoping tests | W3, W5, W13 | Planned |
| FR-02 | Brief creation | Invalid limits rejected; same idempotency key + same body returns the same run; same key + different body returns 409 | `test_contract_models::TestBrief` (done); idempotency API test | W3–W4 | Contract (validation); idempotency planned |
| FR-03 | Planning | Reject cycles, unknown references, unsupported tools and over-limit plans; the planner cannot expand the allowlist | `test_contract_plan.py` | W6 | Contract |
| FR-04 | Human approvals | Decisions bind to version and digest; edits invalidate approval; permission checked at decision time; rejected plan → new version; rejected report not exportable | `test_contract_models::TestApproval`, `spike S1/S4` | W6, W8 | Spike (no authz yet) |
| FR-05 | Research and retrieval | Source has stable ID, URL or upload ref, retrieval time, hash, title and locator; publication date separate from retrieval date; failed fetches recorded, never presented as read | `test_contract_models::TestEvidence`; fetcher tests | W5 | Contract (shape) |
| FR-06 | Drafting | Verifiable claims cite run evidence; inference and recommendations distinguished; missing evidence stated | `test_claim_evidence_rules`; evaluation rubric | W8, W11 | Contract (shape) |
| FR-07 | Review and citation validation | Unknown or unauthorized evidence IDs rejected; support checked semantically; exhausted revisions → NEEDS_ATTENTION | `test_citation_validation_*`, `test_review_routing_is_bounded`; reviewer evaluation | W8 | Contract (deterministic part) |
| FR-08 | Durable execution | Kill the worker after the evidence commit and before the report; restart without duplicate evidence or report versions | `spike S2` (4 crash windows) | W9 | Spike |
| FR-09 | Resource controls | Reserve estimated spend before concurrent calls; reconcile afterwards; stop scheduling when funds are insufficient | Budget-race test with N concurrent reservations | W7, W10 | Planned |
| FR-10 | Progress and cancellation | SSE replay from cursor with no lost events; cancellation stops new work; UI distinguishes requested from completed cancellation | SSE reconnect test; cancel-during-research test | W4, W9 | Contract (state machine); planned |
| FR-11 | Reporting and audit | Immutable versions; approved export generated server-side from the approved version; draft exports watermarked; audit logs carry no secrets or full source text | Export tests; log-redaction test | W8, W10 | Planned |
| FR-12 | Retention and deletion | Documented policy; deletion removes active copies and blocks access; backup expiry documented | Deletion test; runbook review | W13 | Planned |

## Release gates (proposed targets, not claims)

| Gate | Target | How measured | Milestone |
| --- | --- | --- | --- |
| API p95 | < 500 ms for metadata endpoints at 20 concurrent clients | Documented load test, with infra/workload/date recorded | W14 |
| Throughput | 5 concurrent end-to-end runs without corruption, budget races or leakage | Concurrent fake-provider runs | W14 |
| Recovery | 10/10 crash scenarios preserve committed results with no duplicate artifacts | Crash-injection suite (S2 is the seed: 4 windows) | W9 |
| Citation integrity | 100% of citation IDs resolve to evidence authorized for the run | `validate_citations` on every draft | W8 |
| Evidence support | ≥ 90% of sampled claims supported, with denominator and uncertainty reported | Blind human sample | W11 |
| Completion | ≥ 90% of answerable briefs produce a reviewable draft; abstentions scored separately | Evaluation harness | W11 |
| Control tests | 0 unauthorized tool calls or cross-workspace disclosures in the adversarial suite | Adversarial suite | W13 |
| Operability | Backup restore, rollback, readiness checks and provider-failure alerts tested | Runbook drills | W12–W14 |
