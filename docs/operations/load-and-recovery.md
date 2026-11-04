# Load, concurrency and recovery results

Measured on **2026-11-04** with `backend/scripts/loadtest.py` and
`backend/scripts/backup_restore_drill.py`. Raw results:

- [load-results/2026-11-04-local-load.json](load-results/2026-11-04-local-load.json)
- [load-results/2026-11-04-restore-drill.json](load-results/2026-11-04-restore-drill.json)

## What was measured, and what was not

- **Environment:** one developer laptop: Windows 11, 14 logical CPUs, Python 3.14.7,
  PostgreSQL 17.11 on the same machine (portable build, default settings). The API, 2 workers,
  the database and the load generator shared that machine.
- **Workload:** **fake agents and fake search**. These numbers measure the *platform*: HTTP,
  authorization, database, leases, checkpoints and SSE. They do not measure model or web
  latency. With a real model, workflow time is dominated by provider calls and would be
  minutes, not seconds.
- **Isolation:** an isolated database `aos_load`, dropped and recreated per run (the script
  refuses any other name). The deployed environment was **not** load-tested; Render
  performance is unknown.
- **Humans are simulated:** test clients approve immediately. Workflow times below are
  *automated* time only (planning, research to review, finalization), excluding waits for a
  human.

Re-run it from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.loadtest --clients 20 --duration 30 --runs 5 --workers 2 --out <file>
.\.venv\Scripts\python.exe -m scripts.backup_restore_drill --source-db aos_load --out <file>
```

## Results

### Phase A: 5 concurrent workflows, 2 workers

| Measure | Result |
| --- | --- |
| Runs succeeded | **5 / 5** |
| Automated time per run, median / max | 1.13 s / 1.34 s |
| Peak database connections | 17 |

### Phase B: API read latency, 20 concurrent clients for 30 s

Endpoints: `/auth/me`, the runs list, run detail, timeline and evidence; all authorized,
database-backed.

| Measure | Result |
| --- | --- |
| Requests | 6,800 (226.7 per second) |
| Errors (5xx or network) | **0** (all 200) |
| Latency p50 / p95 / p99 / max | 80.4 / **158.3** / 183.9 / 381.7 ms |
| Slowest endpoint p95 | run detail, 163.4 ms |
| Peak database connections | 26 |

Release gate "API p95 < 500 ms for metadata endpoints at 20 concurrent clients" is **met on
this machine** (158 ms). That is not a claim about other hardware.

### Phase C: mixed load, 20 readers while 5 more workflows run

| Measure | Result |
| --- | --- |
| Reads | 6,731, 0 errors, p95 158.4 ms |
| Workflows | **5 / 5** succeeded; automated time median 1.75 s, max 2.05 s |
| Peak database connections | 26 |

### Integrity after phases A and C (10 runs)

| Check | Result |
| --- | --- |
| Runs with more report versions than the review limit allows | 0 |
| Duplicate task results | 0 |
| Tool calls left "started" | 0 |
| Runs over the tool-call limit, or over budget | 0 / 0 |
| Budget reservations left unreconciled | 0 |
| Cross-workspace: list another workspace's runs | 404 |
| Cross-workspace: read another workspace's run or evidence (10 attempts) | 0 not 404 |

Release gate "5 concurrent end-to-end runs without corruption, budget races or leakage" is
**met** (twice) for fake providers.

### Resources

| Process | Resident memory after load |
| --- | --- |
| API (uvicorn, 1 process) | 159.5 MB |
| Worker 1 / worker 2 | 186.8 MB / 185.9 MB |

Peak database connections stayed at 26 or below. The API pool allows up to 20, each worker
up to 20, plus checkpointer connections.

### Phase D: recovery

| Scenario | Result |
| --- | --- |
| Graceful worker shutdown (Ctrl+Break / SIGTERM, idle workers) | 0.69 s and 0.60 s |
| Worker killed abruptly after committing 1 research task (`os._exit(137)`), lease 6 s | A healthy worker took over after **5.89 s**; the run reached a reviewable draft 6.13 s after the crash and then SUCCEEDED |
| Duplicates after recovery | 0 duplicate task results |

Takeover time is bounded by the lease length (`AOS_WORKER_LEASE_SECONDS`). The test used 6 s
to keep the run short; the default is 30 s, so expect up to about 30 s after a crash in a
default deployment. The 10-point crash suite (`test_worker_recovery.py`) covers every
workflow boundary in CI.

### Backup and restore drill

| Measure | Result |
| --- | --- |
| Source → target | `aos_load` → fresh `aos_restore_drill` (`pg_dump -Fc` / `pg_restore`, PostgreSQL 17.11) |
| Dump size, dump time, restore time | 120 KB, 0.72 s, 0.80 s |
| Tables compared (public + `lg` checkpoints), total rows | 28, 1,250 |
| Row-count mismatches | **none** |
| Runs, reports and approvals fingerprints (MD5 of ids, versions, digests, decisions) | identical |
| Audit append-only trigger present after restore | yes |
| Application considers the restored schema current | yes |
| Verdict | **PASS** |

The data set is small. The drill proves the procedure and its verification, not restore time
at scale.

## Other reliability behaviour (automated tests, re-run in CI)

| Behaviour | Test |
| --- | --- |
| Worker poll loop survives a database outage (capped backoff) | `test_worker_loop_survives_a_database_outage` |
| Worker waits for migrations before polling | `test_worker_waits_for_migrations_before_starting` |
| Lease expiry and takeover; stale owner cannot write; concurrent claims have one winner | `test_worker_recovery.py` |
| Bounded retries with backoff for transient errors; deterministic failures not retried | `test_transient_errors_retry_with_backoff_then_fail_visibly`, `test_deterministic_step_failure_is_not_retried` |
| Provider timeout or outage: circuit opens, no call or reservation while open | `test_provider_outage_degrades_to_backoff_without_calling_or_reserving` |
| Bounded parallelism and tool-call limits under concurrency | `test_fan_out_is_parallel_but_bounded…`, `test_tool_call_limit_holds_under_parallelism…` |
| Request size and rate limits | `test_oversized_json_bodies_are_rejected_before_parsing`, rate-limit tests |
| Graceful shutdown in the production container (SIGTERM) | CI `deploy-image` (`docker stop` → `"worker stopped"`) |
