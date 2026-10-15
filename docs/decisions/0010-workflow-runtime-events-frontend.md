# 0010: Workflow runtime, live events and frontend architecture

- **Status:** Accepted
- **Date:** 2026-10-15
- **Requirements:** FR-04, FR-08, FR-10, PRD §3.2 and §3.8

## Decisions

1. **The whole workflow exists end to end from M4**, with deterministic fake agents.
   `app/workflow/graph.py` implements:

   planner → plan approval → research → writer → reviewer (bounded rounds) → report approval
   → finalize, with explicit needs-attention exits.

   Later milestones replace the fakes with real agents behind the same `AgentSuite`
   protocols (`app/agents/base.py`) and deepen individual steps. They do not restructure the
   flow.
2. **Agents have no direct I/O.** Research goes through `ResearchTools`
   (`app/tools/research.py`), which:
   - records each external call before making it (`tool_executions`),
   - enforces the source policy on results in code,
   - stores sources and passages with deterministic IDs inside fenced transactions.
3. **Idempotency comes from the data model.** Plan and report versions come from checkpointed
   state. Writes use `ON CONFLICT DO NOTHING`, so the first committed result wins.
   `task_results` makes each research task run at most once per committed outcome, even when
   it found nothing.
4. **The worker** (`python -m app.workers.runner`):
   - claims with a lease;
   - starts a heartbeat thread; if the lease is lost, the run context is marked dead and the
     next fenced write fails fast;
   - reconciles the job state with the checkpoint, then invokes the graph with
     `durability="sync"`;
   - on an interrupt, releases the lease into a `WAITING` state.

   Only `TransientError` is retried, with bounded exponential backoff and jitter.
   `StepFailed` and unexpected exceptions fail the run visibly with a sanitized reason.
   Human waits reset the attempt counter.
5. **Decisions** (`app/services/runs.decide`) run as one transaction: lock the job, require
   the matching wait, recompute the digest of the latest stored artifact, check permission,
   insert the approval, then re-queue with a resume payload. Concurrent and stale decisions
   get 409.
6. **Live events:** `run_events` is the persisted, workspace-scoped timeline. `GET
   /api/v1/runs/{id}/events` is an SSE stream that:
   - replays events after `Last-Event-ID` (EventSource sends it on reconnect),
   - polls the database (the poll interval is configurable),
   - re-checks access on every poll,
   - ends on terminal states.

   `pg_notify` is emitted for a future LISTEN-based push; polling is enough at pilot scale.
7. **Frontend:**
   - React Router 8 with TanStack Query for server state.
   - A same-origin fetch client that adds the CSRF header on unsafe methods.
   - One idempotency key per brief form instance, reused on retries.
   - The report renders from **structured claims**. No model-produced HTML is ever
     rendered, and source URLs become links only for http(s).
   - The timeline coalesces bursts of SSE events into one refetch.

## Verification

- **Backend:** API workflow tests drive the real worker in-process: happy path, idempotency,
  invalid briefs, role separation, stale, duplicate and wrong-kind decisions, plan rejection
  creating v2, report rejection leading to needs-attention, SSE replay and Last-Event-ID
  resume.
- **Worker recovery** (`test_worker_recovery.py`):
  - real subprocesses killed at three crash points; restart only after lease expiry; no
    duplicate evidence, tasks, tool calls or report versions;
  - stale-owner checkpoint writes rejected, with an unfenced-saver negative control;
  - single-winner claims;
  - transient retry then visible failure; deterministic failure not retried;
  - the planner cannot expand the tool allowlist.
- **Frontend:** Vitest unit tests cover the API client, event descriptions, the brief form
  (idempotency key reused on retry) and the run page (role-gated decisions, safe links).
- **Playwright E2E** against an isolated stack (dev IdP, API, worker, Vite, Postgres) covers
  the full analyst → reviewer journey with a reload and replay, and a cross-workspace 404.
