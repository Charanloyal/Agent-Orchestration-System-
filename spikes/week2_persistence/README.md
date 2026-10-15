# Week-2 persistence spike (throwaway)

This answers one question: can a LangGraph workflow pause for human approval, survive worker
crashes and restarts, and resume from PostgreSQL, while preventing stale workers from writing
results **or checkpoints**? Findings are recorded in
[ADR 0007](../../docs/decisions/0007-checkpoint-persistence-and-fencing.md) and
[ADR 0008](../../docs/decisions/0008-job-leasing-and-dispatch.md).

> This is not production code. There is no authentication, the providers are fake, research
> runs sequentially, and the schema is created ad hoc (no Alembic). Week 3+ rebuilds the
> verified patterns properly.

## Scenarios (each is a pytest file)

| File | Scenario |
| --- | --- |
| `test_s1_pause_resume.py` | Plan wait → approval → research → report wait → approval → success, each step in a **separate OS process**; plan rejection creates v2 and stale decisions fail; report rejection → NEEDS_ATTENTION |
| `test_s2_crash_recovery.py` | `os._exit(137)` at four crash windows; restart after real lease expiry; no duplicate evidence or report versions; the interrupted external call is honestly repeated |
| `test_s3_fencing.py` | Single-winner claims; real lease expiry; stale app writes, heartbeats **and checkpoint writes** rejected; the fence blocks takeover until commit |
| `test_s4_approvals.py` | Version and digest binding; four concurrent approvals → one winner; the decision schedules resumption with no worker holding a lease |
| `test_s5_schema_repair.py` | One bounded repair attempt; persistent invalid model output fails the run visibly, without logging the model output |

Layout: `spike/db.py` (schema), `spike/leases.py` (claim, fence, heartbeat), `spike/fenced_saver.py`,
`spike/approvals.py`, `spike/fakes.py`, `spike/graph.py`, `spike/worker.py` (one worker pass, CLI).

## Run it (Windows PowerShell)

Prerequisite: PostgreSQL running locally, with `AOS_SPIKE_DATABASE_URL` set in `backend/.env`
(git-ignored) or in the environment. The spike uses its own database (for example `aos_spike`),
so its ad-hoc tables never collide with the application schema. See the root README section
"1. Database".

```powershell
cd spikes\week2_persistence
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -v
```

The tests create their tables if missing and use fresh random run IDs, so re-runs don't
conflict. Without a database URL the tests are **skipped**, not passed.

Run one worker pass by hand:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\..\..\backend"
.\.venv\Scripts\python.exe -m spike.worker --run-id <run_id> --worker-id w1
```

## Notes

- `langsmith` is a transitive dependency. The spike forces tracing off, disables its pytest
  plugin, and filters one upstream Python 3.14 deprecation warning. All other warnings are
  errors.
- `FencedPostgresSaver` overrides the private `PostgresSaver._cursor`. Re-run `test_s3_fencing.py`
  after any LangGraph upgrade.
