# Release notes: v1.0.0 (draft)

Draft for the GitHub release of tag `v1.0.0`. The tag is created only after the owner
approves; every line marked PENDING is filled in from evidence, never in advance.

## What it is

A multi-agent research system with human oversight: a planner, parallel researchers, a writer
and a reviewer produce a cited report, and a person approves the plan and the exact final
report version before export. Single-origin web app (FastAPI + React), PostgreSQL as the only
coordination medium, durable LangGraph execution, Google sign-in with invitations and access
requests.

## Verified

| What | How | Result |
| --- | --- | --- |
| Backend | ruff, mypy, pytest on PostgreSQL 17 | 514 passed, 1 live test deselected (local, 2026-11-10) |
| Frontend | TypeScript, Vitest, production build | 83 tests passed |
| End to end | Playwright with axe-core (WCAG 2.2 A/AA, light and dark, 360 px, keyboard) | 12 passed |
| Production image | CI `deploy-image`: Render schema, web + worker and single-process topologies, `smoke_prod.py`, health checks, older-build compatibility | PENDING: green CI run on the merged commit |
| Hosted deployment | `smoke_prod.py`, verification table, address check (check 12) | PENDING (needs owner): [rehearsals.md](operations/rehearsals.md) |
| Rollback | Rehearsal 1 (code only), rehearsal 2 (across migration 0010) | PENDING (needs owner) |

## Measured

- **Harness validation with fake agents** (not model quality): 30 runs per system; outcome
  matches 28/30 for A, B and C (93%; 95% Wilson CI 79–98%); citation validity 100%; human gate
  never bypassed; injected URLs never fetched. Identical across systems by construction.
- **Live-model A/B/C comparison:** PENDING (needs owner budget; ADR 0005 caps it at USD 10).
- **Blind human scoring (two scorers, Cohen's kappa):** PENDING.

## Limitations

- No evidence yet about model quality; the thesis question (does orchestration help?) is open.
- The hosted demo uses deterministic fake agents and is labelled so in the UI.
- The hybrid Render service sleeps after 15 idle minutes; the first request is slow.
- Original uploaded files are not kept on Render (ADR 0026); search and reports use the
  extracted text.
- Load and recovery figures come from one laptop with fake providers.
- Interviews, the usability study and the screen-reader session have not been run.

Full detail: [CHANGELOG](../CHANGELOG.md) and the [final report](report/final-report.md).
