# Documentation

## Milestone status

| Milestone (PRD week) | State | Evidence |
| --- | --- | --- |
| Day 1: health-check skeleton | Done | browser-verified |
| W1: scope and evaluation planning | Documents done. **User interviews NOT DONE** (project lead) | [product/](product/) |
| W2: contracts and architecture spikes | Done. OIDC is now covered by M3; search/fetch and PDF move to M5 | ADR 0006–0008 |
| **M3 / W3: backend foundation** | **Done** | ADR 0009; `backend/tests/test_authz.py`, `test_auth_oidc.py`, `test_migrations.py` |
| **M4 / W4: thin end-to-end slice** | **Done** (fake agents) | ADR 0010; `test_workflow.py`, `test_worker_recovery.py`, `frontend/e2e/` |
| **M5: evidence ingestion** | **Done** | ADR 0011; `test_research_sources.py`, `test_fetcher.py`, `e2e/documents.spec.ts` |
| **M6: LLM planner and plan editing** | **Done** | ADR 0012; `test_planner_llm.py` |
| **M7: parallel research and budgets** | **Done** | ADR 0013; `test_research_budgets.py` |
| **M8: writer, reviewer loop, export** | **Done** | ADR 0014; `test_review_export.py`, `e2e/workflow.spec.ts` |
| **M9: recovery and cancellation** | **Done** | ADR 0015; `test_cancel_retry.py`, 10-scenario crash suite in `test_worker_recovery.py` |
| **M10: observability and cost operations** | **Done** | ADR 0016; `test_observability.py`, [operations/](operations/) |
| M11–M16 | Not started | see the plan in [handoff.md](handoff.md) |

### Implemented behavior (verified by tests)

- **Identity:**
  - OIDC sign-in (authorization code + PKCE) against any compliant issuer.
  - A local dev issuer for demos and tests.
  - Server-side sessions; CSRF and Origin checks on every unsafe request.
- **Tenancy:**
  - Workspaces, memberships and roles (analyst, reviewer, admin), with a single permission
    table.
  - Non-members get 404 on every resource route (auto-generated matrix test).
  - The last admin is protected.
- **Platform:**
  - SQLAlchemy 2 models with Alembic migrations (upgrade/downgrade and model-drift tests).
  - Liveness and readiness endpoints.
  - JSON logs with request IDs and secret redaction; security headers.
  - Consistent error envelope that never echoes input.
- **Contracts:** typed workflow contracts (`backend/app/contracts/`) with drift-checked JSON
  Schemas.
- **Workflow (fake agents):**
  - Idempotent brief submission.
  - LangGraph workflow: plan approval → research → writer → bounded review → report
    approval.
  - Leased, fenced, heartbeating workers with crash recovery.
  - Version- and digest-bound decisions.
  - Persisted timeline with SSE replay.
  - Evidence with provenance.
- **Observability (M10):**
  - OpenTelemetry traces with allowlisted, redacted attributes.
  - Prometheus `/metrics` with database-derived workflow gauges.
  - Rate limits; provider circuit breaker (degraded mode).
  - Workspace usage page; alert rules and an incident runbook.
- **Recovery and cancellation (M9):**
  - Cancel: stops at the next step, tool-call or billable boundary, or immediately when no
    worker is executing.
  - Retry: resumes a failed run from its last checkpoint without redoing research; capped
    at 3.
  - Attempts reaper; per-segment deadlines.
  - On takeover, settles abandoned calls and reservations as possibly billed.
  - A 10-scenario OS-level crash suite.
- **Writer, reviewer and export (M8):**
  - Evidence-only LLM writer.
  - Two-layer review: deterministic numeric and lexical checks, plus an optional model
    reviewer; merged outcomes can only get stricter.
  - Findings persisted per version and round, with a review panel and highlighting of
    flagged claims.
  - Markdown export: approved only for an approved version and digest, otherwise
    watermarked as a draft; escaped text; http(s)-only links; recorded and audited.
- **Research and budgets (M7):** bounded parallel fan-out by dependency level; tool-call limit enforced under a row lock; transactional budget reservations before every LLM/search call with reconciliation; exhaustion → needs attention; LLM researcher citing only provided passages; usage endpoint and cost card.
- **Planner (M6):** OpenAI-compatible adapter with classified errors; schema-validated output with one bounded repair; versioned prompts and per-artifact provenance; plan editing as new versions; approval-wait expiry.
- **Evidence ingestion (M5):** Tavily, offline-corpus and fake search; SSRF-safe pinned fetcher; isolated text-PDF extraction; uploads with content sniffing; workspace-scoped full-text retrieval; failed sources shown as not read.
- **Frontend:**
  - Sign-in, workspace shell, runs list, brief form.
  - Run page with live timeline, plan view, cited structured report with evidence panel,
    and role-gated approvals.
- **Delivery:**
  - ruff and `mypy --strict`.
  - GitHub Actions: backend on Postgres, spike, frontend typecheck/test/build, Playwright
    E2E, container builds.
  - Dockerfiles and `docker-compose.yml` (API, worker, dev IdP, web, Postgres).

### Not implemented yet

- Evaluation runs, retention/deletion, load tests. All four agents are LLM-backed when
  `AOS_AGENT_MODE=llm`; fakes are the default.

## Product and planning

- [Project brief](product/project-brief.md) · [Interview guide](product/interview-guide.md) (**interviews not yet run**)
- [Acceptance criteria matrix](product/acceptance-criteria.md) · [Evaluation plan](evaluation/evaluation-plan.md)
- [Threat model](security/threat-model.md) · [Risk register](risk-register.md)

## Architecture

- [Data model sketch](architecture/data-model.md) · [Deferred spikes](architecture/deferred-spikes.md)
- [Contract JSON Schemas](contracts/)

## Architecture decision records

| ADR | Title | Status |
| --- | --- | --- |
| [0001](decisions/0001-local-health-check-scaffold.md) | Local health-check scaffold | Accepted |
| [0002](decisions/0002-model-provider.md) | Model provider: OpenAI-compatible adapter | Accepted |
| [0003](decisions/0003-search-provider.md) | Search provider: Tavily + offline corpus | Accepted |
| [0004](decisions/0004-deployment-target.md) | Deployment target: local production-like | Accepted |
| [0005](decisions/0005-spending-ceiling.md) | Spending ceiling: USD 10 | Accepted |
| [0006](decisions/0006-workflow-and-contracts.md) | Workflow state machine and contracts | Accepted |
| [0007](decisions/0007-checkpoint-persistence-and-fencing.md) | Checkpoint persistence and fencing | Accepted |
| [0008](decisions/0008-job-leasing-and-dispatch.md) | Job leasing, dispatch and approval resumption | Accepted |
| [0009](decisions/0009-identity-sessions-authorization.md) | Identity, sessions and workspace authorization | Accepted |
| [0010](decisions/0010-workflow-runtime-events-frontend.md) | Workflow runtime, live events and frontend architecture | Accepted |
| [0011](decisions/0011-evidence-ingestion-retrieval.md) | Evidence ingestion: search, safe fetching, extraction, uploads, retrieval | Accepted |
| [0012](decisions/0012-llm-structured-output-plan-editing.md) | LLM adapter, structured output, prompt versioning, plan editing, expiry | Accepted |
| [0013](decisions/0013-parallel-research-budgets.md) | Bounded parallel research, tool-call limits, budget reservations | Accepted |
| [0014](decisions/0014-writer-reviewer-export.md) | Writer, reviewer loop, persisted findings, report export | Accepted |
| [0015](decisions/0015-cancel-retry-recovery.md) | Cancellation, retry, reaper, segment deadlines, crash suite | Accepted |
| [0016](decisions/0016-observability-rate-limits.md) | Observability, rate limits, degraded mode, usage views | Accepted |

## Session handoff

[handoff.md](handoff.md) records the verified state, decisions and blockers.
