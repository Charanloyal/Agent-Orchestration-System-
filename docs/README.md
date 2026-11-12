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
| **M11: evaluation harness** | **Done** (fake-agent validation only; live run awaits a key and budget approval) | ADR 0017; `test_evaluation.py`, [eval/results](../eval/results/README.md) |
| **M12: controlled pilot and deployment packaging** | **Done** (repository side; the Render deploy itself needs an account, payment and an identity provider) | ADR 0018; `test_pilot_and_lifecycle.py`; CI `deploy-image`; [demo script](demo/demo-script.md), [deploy-render.md](operations/deploy-render.md), [P0 checklist](operations/p0-checklist.md) |
| **M13: retention, deletion, audit** | **Done** | ADR 0019; `test_pilot_and_lifecycle.py`; [data-retention.md](operations/data-retention.md) |
| **M14: reliability, load, recovery** | **Done** (local machine, fake providers) | [load-and-recovery.md](operations/load-and-recovery.md); `scripts/loadtest.py`, `scripts/backup_restore_drill.py` |
| **M15: UX, accessibility, user documentation** | **Done** | `RunPage.test.tsx`, `ActivityPage.test.tsx`, `e2e/workflow.spec.ts`; [user guide](user-guide.md) with screenshots from `e2e/screenshots.spec.ts`; [troubleshooting](troubleshooting.md) |
| M16: final report | **Done** (report written from measured results; the live and held-out evaluation are **blocked**: no API key, budget approval or human scorers) | [report/final-report.md](report/final-report.md), [appendices](report/appendices.md) |
| **v1.0 phase 1: sign-in** | **Done** | ADR 0021 §8; `test_auth_oidc.py` (login binding, friendly errors, Google issuer forms, `/auth/config`) |
| **v1.0 phase 2: deployment** | **Done** (repository side) | ADR 0020, 0022, 0023; `test_migrations.py`, `test_smoke_prod.py`, `test_serve.py`, `test_blueprints.py`; `render.hybrid.yaml`, `render.free.yaml`; CI `deploy-image` |
| **v1.0 phase 3: access model** | **Done** | ADR 0021; migration 0010; `test_access.py`, `test_authz.py` |
| **v1.0 phase 4: UI** | **Done** | Onboarding, workspace settings, access administration, notifications, 401/403 handling, dark mode, 360 px; Vitest 79 tests; E2E `access.spec.ts`, `a11y.spec.ts` (axe) |
| v1.0 phase 5: redeploy and rehearsals | **Blocked by owner** (Render and Google accounts) | Procedure: [deploy-render.md](operations/deploy-render.md); records: [rehearsals.md](operations/rehearsals.md) |
| v1.0 phase 6: live evaluation | **Prepared, not run**: budget USD 0 (2026-11-10); harness, guards and blind kit dry-run with fake agents | ADR 0005; [evaluation plan](evaluation/evaluation-plan.md) (exact commands); [scorer brief](evaluation/scorer-brief.md) |
| v1.0 phase 7: hardening | **Done** for storage (ADR 0022), threat model (T18-T22) and operations runbook; live model mode on Render not requested | [threat-model.md](security/threat-model.md), [runbook.md](operations/runbook.md) |
| v1.0 phase 8: user research | **Prepared; blocked by owner** (participants) | [interview guide](product/interview-guide.md), [usability study](product/usability-study.md), [accessibility checklist](product/accessibility-checklist.md) |
| v1.0 phase 9: close-out | **Done** except the tag, which waits for approval | [CHANGELOG.md](../CHANGELOG.md), [handoff.md](handoff.md) |
| Review fixes G1-G10, F4-F13 (2026-11-10) | **Done on branch `release/deploy-ready`** except G1 (push, PR, CI, merge) and G10 (GitHub settings) | ADRs 0024-0026; [release notes draft](release-notes-v1.0.0.md); [GitHub settings](github-settings.md) |

### Implemented behavior (verified by tests)

- **Identity:**
  - OIDC sign-in (authorization code + PKCE) against any compliant issuer, labelled
    "Continue with Google/Microsoft/…"; Google's two issuer forms accepted.
  - Each sign-in attempt bound to its browser by a short-lived cookie (login CSRF).
  - Every sign-in failure ends on the sign-in page with a specific explanation.
  - A local dev issuer for demos and tests.
  - Server-side sessions; CSRF and Origin checks on every unsafe request.
- **Access model (ADR 0021):**
  - Platform admins (environment), allowlist, in-app access list, invitations, signup modes
    `invite` / `request` / `open`.
  - Public access requests that never reveal whether an email is known; rate-limited.
  - Workspace invitations accepted at first sign-in; removing access signs a person out
    everywhere.
  - Admin routes answer 404 to everyone else.
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
- **Reliability (M14):**
  - Load test: 20 readers p95 158 ms with 0 errors; 10 concurrent workflows; integrity
    and isolation checks.
  - Recovery: crash takeover within the lease; graceful shutdown under 1 s.
  - Backup/restore drill: PASS (local machine, fake providers).
- **Pilot packaging and data lifecycle (M12–M13):**
  - Single-origin production image (API serves the SPA; same image runs the worker; no dev
    issuer) and a Render Blueprint validated against Render's schema.
  - Production refuses unsafe settings; platform admins required; request-size limits.
  - Readiness accepts the code's head or a newer schema that declares the code compatible
    (ADR 0020), so rollbacks across additive migrations work; `/version` names the build.
  - `scripts/smoke_prod.py` checks a deployment from outside; `render.hybrid.yaml` and
    `render.free.yaml` run API and worker in one free service (ADR 0022, 0023); CI starts
    every topology and the build before the newest migration.
  - Admin run deletion including checkpoints and export files; retention sweep;
    append-only audit log with an admin audit view.
  - Seeded demo with a sample run; demo script; P0 checklist; migration and rollback
    procedure.
- **Evaluation (M11):**
  - Dev set frozen (`eval-dev-v1`); 20 held-out briefs written, not yet run.
  - Offline corpus v1: 80 labelled synthetic documents with executable fixtures.
  - Harness for systems A/B/C on the real workflow, with automated metrics and Wilson
    intervals.
  - Blind human-scoring kit with two-scorer agreement.
  - One fake-agent harness-validation run (not a quality result).
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
  - Sign-in with provider label, per-error explanations and a request-access form.
  - Welcome page for people without a workspace (create one, or how to join).
  - Workspace settings: rename, roles, removal with confirmation, invitations.
  - Access administration for platform admins, with a pending-requests badge.
  - Workspace shell, runs list, brief form; run page with a workflow progress stepper, live
    timeline, plan view, cited structured report with evidence panel, and role-gated
    approvals.
  - Admin run deletion with confirmation; admin activity (audit) page.
  - Notifications for every action; an expired session returns to sign-in and back; 403s
    explain what is not allowed.
  - A "Demo agents" badge whenever fake agents are configured.
  - Accessibility: axe-checked WCAG 2.2 A/AA in light and dark mode, skip link, per-page
    titles, text-plus-colour status, reduced-motion support, keyboard confirmations,
    layouts down to 360 px.
- **Delivery:**
  - ruff and `mypy --strict`.
  - GitHub Actions: backend on Postgres, spike, frontend typecheck/test/build, Playwright
    E2E, container builds.
  - Dockerfiles and `docker-compose.yml` (API, worker, dev IdP, web, Postgres).

### Not done (needs people, money or accounts; blocked by owner)

- Live (model-backed) evaluation of systems A/B/C, the held-out run, and blind human
  scoring: these need an API key, budget approval and two scorers.
- User interviews, the usability study and the screen-reader session (participants).
- The Render deployment, its verification and both rollback rehearsals: need Render and
  Google Cloud accounts (and payment for `render.yaml`).

All four agents are LLM-backed when `AOS_AGENT_MODE=llm`; fakes are the default.

## Using the system

- [User guide](user-guide.md) (illustrated) · [Troubleshooting](troubleshooting.md) ·
  [Demonstration script](demo/demo-script.md) (5-minute viva path and full walkthrough)
- [Release notes v1.0.0 (draft)](release-notes-v1.0.0.md) · [GitHub repository settings](github-settings.md)

## Final report

- [Final project report](report/final-report.md): 19 sections, architecture, state,
  sequence and ER diagrams, measured results, limitations and verified references.
- [Appendices](report/appendices.md): commands, hashes, API surface, schemas and defects
  found.

## Product and planning

- [Project brief](product/project-brief.md) · [Interview guide](product/interview-guide.md) (**interviews not yet run**)
- [Usability study](product/usability-study.md) · [Accessibility checklist](product/accessibility-checklist.md)
- [Acceptance criteria matrix](product/acceptance-criteria.md) · [Evaluation plan](evaluation/evaluation-plan.md) · [Blind scorer brief](evaluation/scorer-brief.md)
- [Threat model](security/threat-model.md) · [Risk register](risk-register.md)

## Operations

- [Deploy to Render](operations/deploy-render.md) · [Deployment and rollback records](operations/rehearsals.md)
- [Migrations and rollback](operations/migrations.md) · [Data retention](operations/data-retention.md)
- [Runbook](operations/runbook.md) · [P0 checklist](operations/p0-checklist.md) · [Load and recovery](operations/load-and-recovery.md)

## Architecture

- [Data model sketch](architecture/data-model.md) · [Deferred spikes](architecture/deferred-spikes.md)
- [Contract JSON Schemas](contracts/)

## Architecture decision records

| ADR | Title | Status |
| --- | --- | --- |
| [0001](decisions/0001-local-health-check-scaffold.md) | Local health-check scaffold | Accepted |
| [0002](decisions/0002-model-provider.md) | Model provider: OpenAI-compatible adapter | Accepted |
| [0003](decisions/0003-search-provider.md) | Search provider: Tavily + offline corpus | Accepted |
| [0004](decisions/0004-deployment-target.md) | Deployment target: local production-like | Superseded by 0018 and 0023 (Render) |
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
| [0017](decisions/0017-evaluation-harness.md) | Evaluation harness, systems A/B/C, offline corpus, blind scoring | Accepted |
| [0018](decisions/0018-production-image-render-hardening.md) | Single-origin production image, Render topology, production hardening | Accepted |
| [0019](decisions/0019-data-lifecycle-audit.md) | Data lifecycle: deletion, retention, append-only audit log | Accepted |
| [0020](decisions/0020-schema-compatibility-window.md) | Schema compatibility window for rollbacks across migrations | Accepted |
| [0021](decisions/0021-access-model.md) | Access model: invitations, access requests, platform admins, sign-in hardening | Accepted |
| [0022](decisions/0022-deployment-variants-ephemeral-storage.md) | Deployment variants (free single service) and the ephemeral object store | Accepted |
| [0023](decisions/0023-deploy-topologies-and-ci-proof.md) | Deployment topologies (hybrid chosen), role-specific settings, deploy proof in CI | Accepted |
| [0024](decisions/0024-verified-email-only.md) | Trust only provider-verified email addresses (Entra via `xms_edov`) | Accepted |
| [0025](decisions/0025-client-address-behind-proxy.md) | Client address for rate limits: trusted proxy hops from the right of `X-Forwarded-For` | Accepted |
| [0026](decisions/0026-no-file-copies-on-render.md) | Keep no file copies on Render (`AOS_STORE_FILES=false`); amends 0022 | Accepted |
| [0027](decisions/0027-style-studio-honest-metrics.md) | Style studio: measured metrics, fact-locked rewrite, no detector-evasion claims | Accepted |

## Session handoff

[handoff.md](handoff.md) records the verified state, decisions and blockers.
