# 0007: Checkpoint persistence and fencing strategy

- **Status:** Accepted, based on the Week-2 spike. Re-verify on every LangGraph or
  checkpointer upgrade.
- **Date:** 2026-10-14

## Context

PRD §3.5 requires that a stale worker can never advance a run, including through framework
checkpoint writes. A lease alone isn't enough: a paused worker can wake up after its lease was
taken over.

## What was verified (by reading the installed source and running tests)

All results are from langgraph 1.2.15, langgraph-checkpoint 4.3.0,
langgraph-checkpoint-postgres 3.1.3 and psycopg 3.3.6, on PostgreSQL 17.11 and Python 3.14.7.

1. **Write path.** `PostgresSaver.put`, `put_writes` and `delete_thread` all write through the
   private `self._cursor(pipeline=True)` on the saver's own autocommit connection. Reads use
   `_cursor()` without pipeline. There is **no public hook** for running a check in the same
   transaction as a checkpoint write.
2. **Interrupt and resume.**
   - `interrupt(value)` pauses a node and checkpoints it.
   - `invoke(Command(resume=...), config)` resumes it, **re-executing the node from the start**.
   - `get_state(config).interrupts` lists pending interrupts; `.next` lists pending nodes.
   - `invoke(None, config)` continues from the last checkpoint.
3. **Durability.** `invoke(..., durability="sync")` persists each step before the next starts.
   The spike uses `sync` throughout. `async` (the default) was **not** tested with fencing.
4. **Unfenced saver is unsafe (negative control).** Worker A's lease was taken over by B (token
   1 → 2). A then ran a graph with the stock `PostgresSaver`: it **wrote 3 checkpoints**.
5. **Fenced saver works.** `FencedPostgresSaver` overrides `_cursor(pipeline=True)` to open an
   explicit transaction, run `SELECT fencing_token, state FROM run_jobs … FOR SHARE`, raise
   `StaleOwner` on mismatch, and otherwise run the checkpoint statements in that same
   transaction. Stale owner A wrote **0** checkpoints; current owner B succeeded (spike
   `test_stale_owner_cannot_write_checkpoints`). Writes after the lease was released to an
   approval wait are also rejected.
6. **The fence orders correctly against takeover.** While a fenced write holds `FOR SHARE`, a
   takeover claim (`FOR UPDATE SKIP LOCKED`) skips the row. So a takeover happens either
   before the check (write rejected) or after the commit (new owner sees the write) (spike
   `test_open_fenced_write_blocks_takeover_until_commit`).

## Decision

- Use LangGraph's `PostgresSaver` for checkpoints, wrapped by a **fenced subclass** that checks
  the job's fencing token inside the checkpoint-write transaction.
- Application writes (evidence, reports, events, job transitions) use the same `fenced(conn,
  lease)` transaction helper.
- **Thread ID = run ID.** One checkpoint thread per run.
- Use `durability="sync"` until `async` is tested with fencing.
- Node side effects must be idempotent: deterministic keys, `ON CONFLICT DO NOTHING`, and
  "first committed result wins". LangGraph re-executes interrupted and resumed nodes.

## Risks and fallback

- **Private API dependency (risk R4).** `_cursor` is not public. Pin exact versions. The S3 test
  and the negative control must pass before any upgrade.
- **Fallback if `_cursor` changes:** wrap `put`, `put_writes` and `delete_thread` and reproduce
  the upstream SQL in our own transaction (more internal coupling), or move to a single-writer
  design (a dispatcher process owns all checkpoint writes). Re-run S3 either way.
- **Disabled pipeline mode:** pipeline mode is turned off for checkpoint writes, so there is
  one more round-trip per write. Not measured; measure at Week 14.
