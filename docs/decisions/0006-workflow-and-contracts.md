# 0006: Workflow state machine and agent contracts

- **Status:** Accepted for implementation. Revisit if spikes or evaluation show problems.
- **Date:** 2026-10-14

## Context

The PRD (§3.3, §3.5) defines a controlled workflow:

brief → plan → human plan approval → bounded research → draft → structured review → at most two
review/revision rounds → human approval of the exact report version → export.

Agents must exchange typed, schema-validated data. They must not hold free-form conversations.

## Decisions

1. **Contracts live in `backend/app/contracts/`** as strict Pydantic models: unknown fields are
   rejected, and instances are immutable. JSON Schemas are exported to
   [docs/contracts](../contracts), and a test fails if they drift. The contracts are:
   - `Brief`
   - `Plan`
   - `Source` and `EvidencePassage`
   - `ResearcherOutput`, `WriterOutput` and `ReviewerOutput`
   - `ApprovalDecision`
   - `EvalCase`
2. **Structure versus policy.** Structural rules live in the model, for example:
   - plan DAG validity,
   - claim evidence minimums,
   - `pass` not allowed alongside blocker or major findings.

   Rules that depend on server configuration are separate functions taking server-owned
   inputs, so model output cannot bypass them:
   - `enforce_plan_policy(plan, PlanPolicy)`
   - `validate_citations(draft, authorized_ids)`
3. **Claim kinds:** `fact` (≥ 1 evidence), `inference` (≥ 1 evidence), `conflict` (≥ 2),
   `recommendation` (0+) and `unknown` (0+). Semantic support is checked by the reviewer and by
   human sampling, not by the contract.
4. **Run states and transitions** are an explicit table (`ALLOWED_TRANSITIONS`). Tests prove
   that:
   - terminal states have no exits,
   - every state can reach a terminal state,
   - research cannot start without plan approval,
   - success requires report approval.
5. **Bounded review:** `route_after_review(outcome, round)` allows at most two rounds overall.
   After round 2, any outcome other than `pass` becomes `NEEDS_ATTENTION`.
6. **Cancellation:** active states go to `CANCEL_REQUESTED`, then `CANCELLED` (in-flight calls
   may finish and are recorded). Waiting states and `QUEUED` cancel directly because no work is
   in flight.
7. **Retry** of a failed run creates a new, linked run. Terminal states never transition.
8. **Approvals** bind to `(kind, version, digest)`. The digest is SHA-256 over canonical JSON
   (sorted keys, no whitespace, UTF-8). Any edit changes the digest, which invalidates earlier
   approvals.
9. **Versions are assigned by the server**, never taken from model output.

## Consequences

- Retry and cancellation are modelled but not implemented; that's Week 9.
- Budget fields exist on `Brief`; the reservation logic is Week 7.
- `EXPIRED` for overdue approval waits is in the state table; the deadline scheduler is Week 6.
