# 0016: Observability, rate limits, degraded mode and usage views

- **Status:** Accepted
- **Date:** 2026-10-15
- **Requirements:** NFR observability, FR-09 cost visibility, PRD week 10; threat model T9,
  T10, T15

## Decisions

1. **Traces: OpenTelemetry SDK (1.45.1), off by default.**
   - Set `AOS_OTEL_EXPORTER=console|otlp`. Compose has an `observability` profile with
     Jaeger v2.
   - Spans:
     - one HTTP span per request (route template, status);
     - `worker.pass` with its outcome;
     - `step.<node>` per workflow node (approval interrupts are tagged `interrupted`, not
       errors);
     - `research.task`, with context propagated into the thread pool;
     - `llm.call` (step, model, tokens, estimated cost), `search.call` and `fetch` (domain
       only).
2. **Redaction by construction, at two layers.**
   - `span()` accepts only allowlisted attribute keys and runs string values through the log
     redactor, truncated.
   - `RedactingExporter` re-applies the allowlist to *every* exported span, including spans
     that FastAPI creates itself. It drops span events, so exception messages and stack
     traces never leave the process; errors are recorded by type only.
   - A test runs a whole workflow whose topic contains an API-key-shaped string and asserts
     that no exported attribute contains it or the topic.
3. **Metrics: Prometheus text at `/metrics`, with no extra dependency.**
   - HTTP counters and latency histograms in the API process.
   - Workflow gauges computed from PostgreSQL at scrape time, because workers are separate
     processes:
     - runs and jobs by state, oldest runnable job, expired leases;
     - approvals waiting and time to the first expiry;
     - tool calls by status;
     - committed and uncertain spend, LLM tokens by step;
     - review findings by severity and source.
   - Metrics carry no names, IDs or content.
   - Access: a bearer token (`AOS_METRICS_TOKEN`, constant-time compare) when configured.
     Without a token the endpoint is served only outside production. It is excluded from the
     OpenAPI schema.
4. **Rate limits: fixed windows in PostgreSQL (`rate_limit_counters`, migration 0007).**
   - Limits apply per user to run creation, uploads and exports; per workspace to run
     creation; and per client to login (the IP is hashed and never stored raw).
   - Counting happens in its own transaction, and rejected requests count too.
   - The workspace counter is only touched after membership is verified, so outsiders
     cannot exhaust a team's quota.
   - Responses are `429 rate_limited` with `Retry-After`. Old windows are purged by worker
     maintenance.
5. **Degraded mode: a per-provider circuit breaker in each worker.**
   - After N consecutive *transient* failures the breaker opens, and calls fail fast with
     `TransientError(retry_after=…)`. The run backs off through the normal retry path.
   - After the cooldown a single trial call is allowed (half-open).
   - The breaker wraps the meter, so an open circuit reserves no budget.
   - Invalid output or policy errors do not trip it.
6. **Usage view:** `GET /workspaces/{id}/usage?days=` (permission `usage.read`) and a Usage
   page. It shows totals, uncertain spend, tokens, spend by step and by day, and the most
   expensive runs with their share of budget. Everything is labelled as an estimate.
7. **Operations docs:** alert rules ([alerts.yml](../operations/alerts.yml)) and an incident
   runbook ([runbook.md](../operations/runbook.md)) keyed to those alerts.

## Consequences

- No metrics are scraped from workers. Anything an alert needs is derivable from the
  database, which also survives worker restarts.
- Fixed windows allow up to twice the limit across a window boundary. This is acceptable for
  abuse protection in a pilot; a token bucket would be smoother.
- Breaker state is per process: with several workers, each learns about an outage on its own
  (at most N failed calls each).
