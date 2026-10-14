# Documentation

## Status

| Milestone | State |
| --- | --- |
| Week 1 / Day 1: local health-check skeleton | Done: backend test passes, frontend builds, browser verified |
| Week 1: scope and evaluation planning | Documents done. **User interviews NOT DONE. Provider, deployment and budget decisions UNDECIDED** |
| Week 2: contracts and architecture spikes | Contracts done. Persistence and approval spike done (22 tests on PostgreSQL 17.11). OIDC, search/fetch and PDF spikes **NOT RUN** (blocked on provider decisions) |
| Week 3: backend foundation | Not started |

### Implemented behavior

- `GET /health` (FastAPI) returns `200 {"status": "ok"}`. This is a liveness check only.
- The React page fetches `/health` through the Vite dev proxy. It shows loading, success and
  error states, plus a retry button.
- Typed contracts with structural validation and server-side policy functions, in
  `backend/app/contracts/`. They are not yet used by any API route.

### Demonstrated only in the throwaway spike

- Pause and resume across OS processes.
- Fencing of application and checkpoint writes.
- Approval binding to version and digest.
- Crash recovery without duplicate committed artifacts.
- Bounded schema repair.

See ADRs 0007–0008.

### Not implemented (target architecture only)

- Application database and Alembic migrations.
- Authentication and authorization.
- Production workers.
- Agents on real models.
- Search and fetch, object storage, observability, Docker, CI.

## Product and planning

- [Project brief](product/project-brief.md): hypothesis, personas, domain, P0 boundary,
  example report for the Week-1 exit gate.
- [Interview guide](product/interview-guide.md): **interviews not yet run**.
- [Acceptance criteria matrix](product/acceptance-criteria.md): FR-01..FR-12 and release gates
  mapped to tests.
- [Evaluation plan](evaluation/evaluation-plan.md): metrics, baseline, ablation, leakage rules.
- [Threat model](security/threat-model.md) · [Risk register](risk-register.md)

## Architecture

- [Data model sketch](architecture/data-model.md)
- [Deferred Week-2 spikes](architecture/deferred-spikes.md)
- [Contract JSON Schemas](contracts/)

## Architecture decision records

- [0001: Local health-check scaffold](decisions/0001-local-health-check-scaffold.md) (Accepted)
- [0002: Model provider](decisions/0002-model-provider.md) (Proposed, UNDECIDED)
- [0003: Search provider](decisions/0003-search-provider.md) (Proposed, UNDECIDED)
- [0004: Deployment target](decisions/0004-deployment-target.md) (Proposed, UNDECIDED)
- [0005: Development spending ceiling](decisions/0005-spending-ceiling.md) (Proposed, UNDECIDED)
- [0006: Workflow state machine and agent contracts](decisions/0006-workflow-and-contracts.md) (Accepted)
- [0007: Checkpoint persistence and fencing](decisions/0007-checkpoint-persistence-and-fencing.md) (Accepted, from spike)
- [0008: Job leasing, dispatch and approval resumption](decisions/0008-job-leasing-and-dispatch.md) (Accepted, from spike)

## Session handoff

[handoff.md](handoff.md) records the verified state, decisions and blockers after each session.
