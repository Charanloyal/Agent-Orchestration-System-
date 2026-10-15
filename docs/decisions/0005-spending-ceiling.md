# 0005: Development spending ceiling

- **Status:** Accepted (2026-10-14, project lead).
- **Decision:** **USD 10.00 total** for all live LLM and search calls during the project, tracked by the estimated-vs-reconciled cost ledger. Every live session is approved before it runs.
- **Date:** 2026-10-14

## Context

PRD §6 requires a personal spending ceiling set in Week 1, before any paid call. The
non-negotiable requirements forbid live-model tests without an explicit budget. Provider
billing caps are not guaranteed; our reservation ledger tracks *estimated* spend.

## Proposed policy (applies whatever the amount)

1. **Default: zero paid calls.** CI, unit tests and the spike use fake providers only.
2. Every live run or smoke test needs a recorded budget (amount, currency, purpose, approver)
   and is labelled "live" in its results.
3. Set provider-side spending limits or alerts where offered. Treat them as alerting, not as a
   guaranteed cap.
4. Record the price schedule (with date) used for each estimate. Reconcile actual usage after
   every live session.
5. Stop and ask before any action that would exceed the ceiling, including retries.

## Options for the amount

Choose after ADR 0002 and ADR 0003 give real prices:
- **(a)** a monthly ceiling that covers the Week-11 evaluation (40 cases × 3 systems, plus
  repeats) with headroom, or
- **(b)** a smaller ceiling for development only, plus a separate one-off evaluation budget
  approved before Week 11.

## Consequences

Until a ceiling is recorded here, no live provider calls are made.

**Decision owner:** project lead.
