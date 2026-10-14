# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: Week 1 (scope and evaluation) + Week 2 (contracts and persistence spike), complete except the items marked NOT DONE / NOT RUN below.

Last completed vertical slice:
  Typed workflow contracts plus a LangGraph/PostgreSQL spike: pause for plan approval →
  resume in a new process → research (fake) → write → review → pause for report approval →
  succeed. Includes crash recovery and stale-owner fencing of app and checkpoint writes.

Files changed:
  backend/app/contracts/*            new: Brief, Plan, Source/Evidence, agent outputs, RunState, approvals, EvalCase
  backend/scripts/export_schemas.py  new: JSON Schema export
  backend/tests/test_contract_*.py   new: 93 contract/schema/brief tests
  docs/contracts/*.schema.json       new: generated schemas (drift-tested)
  docs/product, docs/evaluation, docs/security, docs/architecture, docs/risk-register.md  new
  docs/decisions/0002..0008          new ADRs
  eval/briefs/dev/dev-01..20.json    new: development briefs; eval/briefs/heldout/README.md (procedure only)
  spikes/week2_persistence/*         new throwaway spike (own pinned requirements)
  README.md, docs/README.md          updated

Architecture decisions accepted:
  0006 workflow state machine and contracts; 0007 fenced PostgresSaver subclass
  (overrides the private _cursor) with durability="sync"; 0008 PostgreSQL leases with
  fencing tokens; approval transaction schedules resumption.
  Proposed / UNDECIDED: 0002 model provider, 0003 search provider, 0004 deployment
  target, 0005 spending ceiling.

Database migrations added/applied:
  None (Alembic starts in Week 3). The spike creates its own tables (CREATE TABLE IF NOT
  EXISTS) in the local database aos_spike; LangGraph checkpoint tables are created via
  PostgresSaver.setup().

Tests actually run and results (2026-10-14, Windows, Python 3.14.7):
  backend:  pytest → 94 passed (1 health + 93 contract/schema/dev-brief tests)
            schema drift test confirmed failing on a modified schema, then restored
  spike:    pytest → 22 passed in ~43 s against PostgreSQL 17.11 on 127.0.0.1:54329
            negative control (stock PostgresSaver): stale owner wrote 3 checkpoints;
            fenced saver: 0
  frontend: npm run build → success (unchanged since Day 1)

Checks not run:
  User interviews (3–5)                NOT DONE: project lead
  Human judgement of example report    NOT DONE: project lead
  Held-out briefs                      NOT WRITTEN by design (leakage procedure)
  OIDC, search/fetch, text-PDF spikes  NOT RUN: provider decisions pending (docs/architecture/deferred-spikes.md)
  durability="async" with fencing      NOT TESTED
  Any live model/search call           NONE MADE

Observed performance/cost, with workload and date:
  None measured. Spike timings are not performance data. No provider cost incurred.

Known bugs and security/reliability gaps:
  - No authentication or authorization anywhere (spike records decided_by, doesn't check it).
  - Fencing depends on private PostgresSaver._cursor (risk R4); re-run S3 on upgrade.
  - Spike research is sequential; no heartbeat thread, attempts reaper, cancellation,
    approval deadlines or budget reservations yet.
  - Local PostgreSQL binaries are unsigned with no published checksum (risk R11); local only.
  - Package installs need an approved PyPI/npm mirror (corporate NTLM proxy, risk R10).
  - One upstream deprecation warning (langsmith, Python 3.14) is filtered in the spike only.

Unresolved choices:
  Model provider, search provider, deployment target, spending ceiling, identity provider
  for OIDC; whether the pilot domain survives the interviews.

Next bounded task:
  Week 3: backend foundation. SQLAlchemy models and Alembic migrations from
  docs/architecture/data-model.md, workspace/membership authorization, settings/secrets
  handling, CI with lint/type-check/tests, Docker Compose for API + PostgreSQL.

Acceptance criteria for next task:
  - Fresh checkout starts from documented commands (Compose or local).
  - Alembic upgrade/downgrade runs cleanly on an empty database.
  - Cross-workspace API tests pass for every exposed route (FR-01).
  - CI runs backend tests, the contract-schema drift test, and the frontend build.
```
