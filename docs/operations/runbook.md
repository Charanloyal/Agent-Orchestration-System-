# Incident runbook (local controlled pilot)

Each section matches an alert in [alerts.yml](alerts.yml). Every step uses this repository's
tools. Commands assume PowerShell in `backend/` with the venv; on Docker Compose prefix them
with `docker compose exec api`.

**First, for any incident:**

1. Note the time.
2. Open `/metrics`.
3. Search the JSON logs for the `request_id` or `run_id` users report. Logs and traces carry
   IDs and counts only, never source text, prompts or secrets.

## API down

1. Run `curl http://127.0.0.1:8000/healthz`. If there is no answer, the process is down:
   restart it (`uvicorn app.main:app` or `docker compose restart api`).
2. Run `curl http://127.0.0.1:8000/readyz`. A 503 means the database is unreachable or not
   migrated:
   - Check PostgreSQL is running.
   - Run `alembic current`, then `alembic upgrade head` if a deploy skipped migrations.
3. Runs are durable: nothing is lost while the API is down. Workers keep processing, and
   SSE clients reconnect and replay from `Last-Event-ID`.

## API errors

1. Find failing routes:

   ```
   sum by (route, status) (rate(aos_http_requests_total{status=~"5.."}[5m]))
   ```

2. Search the logs for `"status": 500` on that route and take the `request_id`. The
   matching exception log line has the stack trace; the response body never does.
3. If one release introduced the errors, roll back: redeploy the previous image or
   commit. Migrations are additive, so the previous code runs on the newer schema.

## Worker down or stalled

Symptoms are `aos_jobs_expired_leases > 0` (a worker died mid-run) or a growing
`aos_jobs_oldest_queued_seconds` (no worker is running).

1. Check the worker process (`docker compose ps worker`) or its log for `worker started`.
2. Start or restart it. Recovery is automatic: the next claim takes over expired leases.
   Committed tasks, reports and reviews are reused, and interrupted calls are recorded as
   `abandoned` or `uncertain` (ADR 0015).
3. A job that crashes its worker on every attempt is failed by the reaper ("worker crashed
   or stalled on N attempts"). Reproduce it with the run's brief. After the fix, an analyst
   presses **Retry from last checkpoint**.

## Runs failing

1. Open the failed run. The banner shows `step: reason`; the timeline shows `step_failed`.
2. Common causes:
   - **`invalid model output after 2 attempts`**: the model ignored the JSON schema twice.
     Check `prompt_version` and the model in the run's provenance. Retry once; if it
     persists, switch to a stronger model in `AOS_LLM_MODEL`.
   - **`transient errors persisted after N attempts`**: see Provider outage.
   - **`plan violates policy`**: the planner proposed tools the brief does not allow. This
     is working as designed; edit the plan or the brief.
3. Retries are capped at 3 per run. Beyond that, submit a new brief.

## Provider outage

Symptoms are `retry_scheduled` events mentioning `circuit open`, a growing
`aos_budget_uncertain_usd_total`, or provider 5xx and timeouts in the logs.

1. The circuit breaker already stops calls for `AOS_BREAKER_COOLDOWN_SECONDS` after
   `AOS_BREAKER_FAILURE_THRESHOLD` consecutive failures. Runs back off; they are not lost
   and are not billed while the circuit is open.
2. Check the provider's status page.
3. For a long outage:
   - Pause new work by stopping the worker; runs stay queued.
   - Or switch providers: `AOS_LLM_BASE_URL` and `AOS_LLM_MODEL` for any OpenAI-compatible
     endpoint, or `AOS_SEARCH_PROVIDER=corpus` for the offline corpus.
4. Compare uncertain spend with the provider's billing console. Uncertain amounts are
   estimates kept on purpose; never delete them to make the numbers look better.

## Spend ceiling

The project ceiling is USD 10 (ADR 0005).

1. Stop the worker (`docker compose stop worker`) to stop new billable calls immediately.
2. Open **Usage** and find the most expensive runs. Check whether a brief's
   `max_estimated_cost` is too high.
3. Reconcile with the provider's invoice before resuming. Resume only with written approval
   from the project lead.

## Approval backlog

Symptom: `aos_approvals_seconds_to_first_expiry < 6h`.

1. List waiting runs (state *Awaiting plan approval* or *Awaiting report approval*) and
   remind the analysts or reviewers.
2. Expired runs are final (state EXPIRED); the analyst resubmits the brief. The approval TTL
   is `AOS_APPROVAL_TTL_HOURS` (default 72).

## Suspected secret exposure

1. Rotate the secret at the provider first. Then update `backend/.env` or the deployment
   secret store and restart the API and worker.
2. Search the logs for the old value's prefix. The redactor masks known shapes (API keys,
   bearer tokens, URL credentials). Report any unmasked occurrence as a bug with a test.
3. Record the incident in `docs/risk-register.md`.

## Rate limiting complaints

`429 rate_limited` responses carry `Retry-After`. Limits are per user and per workspace
(`AOS_RATE_*` settings) and are stored in `rate_limit_counters`. Raise a limit only after
confirming the traffic is legitimate. Outsiders cannot consume a workspace's quota.
