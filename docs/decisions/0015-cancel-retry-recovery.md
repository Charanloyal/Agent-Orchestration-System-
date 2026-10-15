# 0015: Cancellation, retry, reaper, segment deadlines and the crash suite

- **Status:** Accepted
- **Date:** 2026-10-15
- **Requirements:** FR-10 (cancel, retry, recovery), PRD §3.5 state machine; threat model T9, T10

## Context

M4 provided leases, fencing and crash recovery for three crash points. The pilot also needs:

- **Cancellation** that a human can rely on.
- **Recovery** from deterministic failures without redoing paid work.
- **No stuck jobs** when a worker crashes on every attempt.
- **Enforcement** of the brief's deadline.
- **Proof** of the at-least-once guarantees across the whole workflow, not just three
  points.

## Decisions

1. **Cancellation is cooperative at boundaries, and immediate when nobody is working.**
   - `POST /runs/{id}/cancel` (analyst or admin) locks `run_jobs` then `runs`, in the same
     order as fenced writes.
   - If a worker holds the lease, the run becomes `CANCEL_REQUESTED`.
   - Otherwise (queued, backing off after a transient error, or waiting for a human), it
     goes straight to `CANCELLED` and the job is closed. A late approval then gets 409.
   - Repeated cancels are idempotent.
2. **Boundaries** (`RunContext.check_continue`) run inside the transactions that start new
   work:
   - Every step transition.
   - Every tool call (`_start`, under the run-row lock).
   - Every budget reservation (before every billable call).
   - The start of each worker pass and the release to an approval wait.

   Raising `RunStopped` ends the pass. Results of calls already in flight are still recorded;
   the PRD allows them to finish.
3. **Segment deadline.** `deadline_minutes` bounds each automated segment, not human waits
   (they have the approval TTL). A decision or retry restarts the segment; a boundary past
   the deadline ends the run as `EXPIRED`.
4. **Retry re-opens only `FAILED` runs.**
   - The run returns to the state it failed in, taken from the `state_changed` event. That
     is the only transition out of a terminal state: `RETRYABLE_FROM` contains no waits and
     no `CANCEL_REQUESTED`.
   - The job is re-queued with fresh attempts, and the worker resumes from the last
     committed checkpoint. Completed research is not redone (tested by counting tool calls).
   - Manual retries are capped at 3 per run.
5. **Attempts reaper.** Each claim counts an attempt, so a job whose lease expired after its
   last allowed attempt would never be claimed again. Worker maintenance:
   - Fails such runs visibly ("worker crashed or stalled on N attempts"); a pending cancel
     still wins.
   - Bumps the fencing token so a zombie owner cannot write.
   - Marks the job's started tool calls `abandoned`.
6. **Recovery settles what a dead owner left behind.** On every claim, tool calls and budget
   reservations from older fencing tokens become `abandoned` and `reconciled + uncertain`
   (estimate as actual), and are surfaced in the timeline. Money that may have been spent is
   never silently released.
7. **The first committed result wins, without a second call.** A re-executed writer reuses
   the committed report version, and a re-executed reviewer reuses the committed review
   (event plus findings). A crash therefore never pays for a second draft, and a model can
   never answer differently on replay.

## Crash suite (real OS processes, `os._exit(137)`)

| # | Crash point | Recovery verified |
| --- | --- | --- |
| 1 | `after_plan_commit` | one plan version, one `plan_proposed`, awaiting approval |
| 2 | `before_release_to_wait` | interrupt reconciled to a wait, no duplicate plan |
| 3 | `after_tool_start` | interrupted call `abandoned`; committed tasks not re-run |
| 4 | `after_budget_reserve` | stale reservation settled `uncertain`; nothing left `reserved` |
| 5 | `after_task_commit` | committed task keeps its tool-call count; siblings complete |
| 6 | `after_research` | evidence and tasks unchanged |
| 7 | `before_writer` | one report version |
| 8 | `after_report_commit` | committed version reused (no second draft) |
| 9 | `after_review_commit` | committed review reused; one `review_completed` |
| 10 | `before_finalize` | one `SUCCEEDED` transition; decisions intact |

The existing tests also still pass: concurrent claims with one winner, stale-owner checkpoint
fencing with a negative control, and the transient-retry and deterministic-failure
classification.

## Consequences

- Cancellation latency is bounded by the longest in-flight call (model or fetch timeout), not
  by the remaining work. The UI says "Stopping" until the worker confirms.
- A retry can fail again in the same way. The cap and the visible reason keep this honest;
  NEEDS_ATTENTION runs are not retryable (they need a new brief or budget).
