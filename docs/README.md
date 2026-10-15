# Documentation

## Milestone status

| Milestone (PRD week) | State | Evidence |
| --- | --- | --- |
| Day 1: health-check skeleton | Done | browser-verified |
| W1: scope and evaluation planning | Documents done. **User interviews NOT DONE** (project lead) | [product/](product/) |
| W2: contracts and architecture spikes | Done. OIDC is now covered by M3; search/fetch and PDF move to M5 | ADR 0006–0008 |
| **M3 / W3: backend foundation** | **Done** | ADR 0009; `backend/tests/test_authz.py`, `test_auth_oidc.py`, `test_migrations.py` |
| M4 / W4: thin end-to-end slice | Not started | |
| M5–M16 | Not started | see the plan in [handoff.md](handoff.md) |

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
- **Delivery:** ruff and `mypy --strict`; GitHub Actions (backend on Postgres, spike, frontend
  build, container builds); Dockerfiles and `docker-compose.yml`.

### Not implemented yet

- Runs, workers and agents.
- Search and fetch, evidence, budgets, the report workflow, observability beyond logs,
  evaluation runs.

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

## Session handoff

[handoff.md](handoff.md) records the verified state, decisions and blockers.
