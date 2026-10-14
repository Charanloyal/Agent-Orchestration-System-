# 0008: Job leasing, dispatch and approval resumption

- **Status:** Accepted, based on the Week-2 spike. Production implementation is Week 9.
- **Date:** 2026-10-14

## Context

Workers claim runs from PostgreSQL with no Redis, Celery or second workflow engine (PRD
§3.1). Approval waits must release the worker. Execution is at least once.

## Decision

1. **`run_jobs` owns dispatch only.** It holds:
   - state (`QUEUED`, `LEASED`, `WAITING`, `DONE`, `FAILED`),
   - lease owner and expiry,
   - a monotonically increasing `fencing_token`,
   - attempts, `available_at`,
   - `waiting_for` and `resume_payload`.

   Graph progress lives only in LangGraph checkpoints (ADR 0007). Check constraints keep lease
   and wait fields consistent with the state.
2. **Claim** uses a single `UPDATE … WHERE run_id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)`.
   It picks up `QUEUED` jobs or `LEASED` jobs whose lease has expired, increments the token and
   attempts, and uses **database time only** (`now()`), so worker clock skew doesn't matter.
   Five concurrent claimers produce exactly one winner (spike S3).
3. **Heartbeat** extends the lease only if the token still matches. A stale heartbeat raises
   `StaleOwner`.
4. **Reconciliation on claim.** The worker compares dispatch state with graph state:
   - no checkpoint → start;
   - pending interrupt + resume payload → `Command(resume=…)`;
   - pending interrupt without a payload → re-record the wait (the crash happened between the
     checkpoint and the wait record);
   - pending nodes → `invoke(None)`;
   - finished → mark done.

   Tool executions a previous owner started but never finished are marked `abandoned`.
5. **Approval waits release the lease.** The worker sets the job to `WAITING` (no owner, no
   expiry) and exits. A waiting job can't be claimed.
6. **A decision is one transaction.** It locks the job row, requires `WAITING` for the right
   kind, recomputes the digest from the stored artifact body, inserts the approval (unique per
   run/kind/version), sets the job to `QUEUED` with `resume_payload = {approval_id}`, and
   records an event. Any worker can then resume the run. Of four concurrent approvals exactly
   one succeeds (spike S4). The resumed node re-checks that the approval binds to the version
   and digest in its own state (defence in depth).
7. **External calls.** Record a `tool_executions` row (`started`) before the call and mark it
   `succeeded` when the result commits.
   - Tasks with committed evidence are skipped on re-execution, so committed work is never
     re-fetched.
   - A crash between an external call and the commit **repeats that call**, and so may repeat
     its cost. Spike S2 demonstrates this; exactly-once is not claimed.

## Verified crash windows (spike S2, separate OS processes, `os._exit(137)`)

| Crash point | After restart |
| --- | --- |
| After the search call, before the evidence commit | 6 evidence rows (no duplicates); 4 tool executions: 1 abandoned, 3 succeeded (the interrupted call repeated) |
| After the evidence commit, before the node returns | 6 evidence rows; 3 tool executions (no repeats); 1 report version |
| Before the writer | Research not re-run; 3 `task_completed` events; 1 report version |
| After the report commit, before the node returns | Still 1 report version; digest unchanged (first committed result wins) |

A restart attempted before the dead worker's lease expired got `no_job` in every case.

## Not yet covered (production work, Week 9)

- Heartbeat thread and lease tuning. The spike uses short single-pass workers.
- Attempts exhaustion: a reaper should move jobs to `FAILED` when `attempts >= max_attempts`.
- Cancellation, approval deadlines (`EXPIRED`) and bounded parallel fan-out. The spike's
  research is sequential.
- Authorization of decisions (`decided_by` is recorded, not checked).
- Notification of idle workers (`LISTEN`/`NOTIFY`) versus polling.
