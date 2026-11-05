# Appendices to the final report

These appendices support the [final report](final-report.md). Commands are written for
Windows PowerShell; on macOS or Linux, replace `.\.venv\Scripts\python.exe` with
`.venv/bin/python` and `npm.cmd` with `npm`.

## A. Reproduction commands

### A.1 Setup

The full instructions are in the [README](../../README.md).

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.cli seed-demo --sample-run
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000   # terminal 1
.\.venv\Scripts\python.exe -m devtools.dev_oidc                   # terminal 2
.\.venv\Scripts\python.exe -m app.workers.runner                  # terminal 3
cd ..\frontend; npm.cmd ci; npm.cmd run dev                        # terminal 4
```

### A.2 The checks reported in Section 13.1

```powershell
# backend/ (database tests need AOS_TEST_DATABASE_URL: a throwaway database)
.\.venv\Scripts\python.exe -m ruff check app devtools evaluation tests scripts migrations\env.py
.\.venv\Scripts\python.exe -m ruff format --check app devtools evaluation tests scripts migrations\env.py
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q

# frontend/ (E2E needs AOS_E2E_DATABASE_URL: wiped and re-seeded)
npm.cmd run typecheck
npx.cmd vitest run
npm.cmd run build
npx.cmd playwright test
$env:AOS_SCREENSHOTS = "1"; npx.cmd playwright test screenshots   # re-captures docs/assets/screenshots
```

### A.3 Evaluation (Section 13.5)

From `backend/`, with `AOS_EVAL_DATABASE_URL` pointing at an empty, dedicated database:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run                         # dev split, A/B/C, fake agents
.\.venv\Scripts\python.exe -m evaluation.blind ..\eval\results\<folder>
.\.venv\Scripts\python.exe -m evaluation.score <folder>\scoring <scorerA> <scorerB>
# Live (costs money; needs written budget approval, ADR 0005):
.\.venv\Scripts\python.exe -m evaluation.run --live --budget 0.50 --cases dev-01 --systems A --repeats 1
# Held-out: once only, after the live dev run:
.\.venv\Scripts\python.exe -m evaluation.run --split heldout --confirm-heldout --live --budget <approved>
```

### A.4 Load test and restore drill (Sections 13.2–13.3)

```powershell
.\.venv\Scripts\python.exe -m scripts.loadtest --clients 20 --duration 30 --runs 5 --workers 2 --out <file>
.\.venv\Scripts\python.exe -m scripts.backup_restore_drill --source-db aos_load --out <file>
```

The load test refuses any database not named `aos_load*`. The drill always restores into a
fresh `aos_restore_drill` database.

## B. Dataset and corpus hashes

| Item | SHA-256 |
| --- | --- |
| Dev cases (`eval/briefs/dev/*.json`, 20 files) | `e9b07361120f204137d424feb178723604d2a77b7a0ea6f793f9374d436be6dd` |
| Held-out cases (`eval/briefs/heldout/*.json`, 20 files) | `828c48823d552bf14b08d76d1d7cc9c4bf0a57f30533a9ba6ef1e8099f81f612` |
| Corpus manifest (`eval/corpus/v1/MANIFEST.json`) | `967f7c066fa5f74d9cf3ed93cb97300417f1de1f3264af54ba16dc717da6e5ea` |

- The dev split is frozen at git tag `eval-dev-v1` (commit `37556c4`).
- The held-out files last changed in commit `6507532` (2026-10-16), before this report.
- The corpus manifest hash equals the one recorded in the M11 result's `config.json`.

The case hashes were computed from the repository root with:

```python
import hashlib, pathlib
def tree_hash(d):
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(d).glob("*.json")):
        h.update(p.name.encode()); h.update(b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n")); h.update(b"\0")
    return h.hexdigest()
print(tree_hash("eval/briefs/dev"), tree_hash("eval/briefs/heldout"))
print(hashlib.sha256(pathlib.Path("eval/corpus/v1/MANIFEST.json").read_bytes().replace(b"\r\n", b"\n")).hexdigest())
```

## C. Where every result is stored

| Result | Location |
| --- | --- |
| Fake-agent harness validation (90 runs) | [eval/results/2026-10-16-dev-validation-fake-16c073/](../../eval/results/2026-10-16-dev-validation-fake-16c073/summary.md) (`config.json`, `runs.jsonl`, `summary.*`, `reports/`, `artifacts/`) |
| Load test (phases A–D) | [docs/operations/load-results/2026-11-04-local-load.json](../operations/load-results/2026-11-04-local-load.json), explained in [load-and-recovery.md](../operations/load-and-recovery.md) |
| Backup/restore drill | [docs/operations/load-results/2026-11-04-restore-drill.json](../operations/load-results/2026-11-04-restore-drill.json) |
| Crash-suite scenarios and expectations | [ADR 0015](../decisions/0015-cancel-retry-recovery.md); `backend/tests/test_worker_recovery.py` |
| Acceptance matrix and release gates | [acceptance-criteria.md](../product/acceptance-criteria.md) |
| Test and CI status per milestone | [handoff.md](../handoff.md); commit messages on `main` |

Raw result files are never edited after they are written. Any rerun gets a new folder or file
with its own date.

## D. API surface

All routes are under the same origin. Unsafe methods need the session cookie, an
`X-CSRF-Token` header and a matching `Origin`. Non-members get 404 on every workspace
resource.

| Method and path | Purpose | Role |
| --- | --- | --- |
| `GET /healthz`, `GET /readyz` | Liveness; readiness (database reachable and at the migration head) | public |
| `GET /metrics` | Prometheus metrics | bearer token |
| `GET /api/v1/auth/login`, `GET /api/v1/auth/callback`, `POST /api/v1/auth/logout` | OIDC code + PKCE sign-in and sign-out | public / signed in |
| `GET /api/v1/auth/me` | Current user, memberships, CSRF token, deployment info | signed in |
| `GET, POST /api/v1/workspaces`; `GET /api/v1/workspaces/{id}` | Workspaces | member |
| `GET, POST /api/v1/workspaces/{id}/members`; `PATCH, DELETE …/members/{user}` | Membership management (the last admin is protected) | admin |
| `GET /api/v1/workspaces/{id}/usage` | Estimated and reconciled spend | analyst, admin |
| `GET /api/v1/workspaces/{id}/audit` | Append-only activity log | admin |
| `POST /api/v1/workspaces/{id}/uploads`; `GET …/uploads`, `GET …/uploads/search`, `GET …/uploads/{upload}`; `DELETE …/uploads/{upload}` | Upload; list, full-text search and read; delete | analyst; member; uploader or admin |
| `POST /api/v1/runs` (with `Idempotency-Key`); `GET /api/v1/runs` | Submit a brief; list runs | analyst; member |
| `GET /api/v1/runs/{id}`; `DELETE /api/v1/runs/{id}` | Run detail; delete a finished run | member; admin |
| `GET /api/v1/runs/{id}/plans/{v}`; `PUT /api/v1/runs/{id}/plan` | Read a plan version; edit (creates a new version) | member; analyst |
| `POST /api/v1/runs/{id}/plan-decisions` | Approve or reject a plan version + digest | analyst |
| `POST /api/v1/runs/{id}/cancel`, `POST /api/v1/runs/{id}/retry` | Cancel; retry a failed run from its checkpoint | analyst |
| `GET /api/v1/reports/{id}/versions/{v}`; `POST /api/v1/reports/{id}/decisions` | Read a report version; approve or reject version + digest | member; reviewer |
| `POST /api/v1/reports/{id}/versions/{v}/export`; `GET /api/v1/runs/{id}/exports` | Markdown export (approved or watermarked draft); export history | member |
| `GET /api/v1/runs/{id}/reviews`, `…/evidence`, `…/sources`, `…/usage`, `…/timeline` | Review rounds, evidence, sources, cost, persisted timeline | member |
| `GET /api/v1/runs/{id}/events` | Server-sent events with `Last-Event-ID` replay | member |

Roles follow the single permission table in `backend/app/policy/permissions.py`. Admins hold
every analyst and reviewer permission. In development, the OpenAPI document is served at
`/api/docs`; it is disabled in production.

## E. Contract schemas

Generated from the Pydantic contracts in `backend/app/contracts/` by
`python -m scripts.export_schemas`. `test_contract_schemas.py` fails if they drift.

| Schema | Describes |
| --- | --- |
| [brief.schema.json](../contracts/brief.schema.json) | Research brief: topic, audience, questions, source policy, limits |
| [plan.schema.json](../contracts/plan.schema.json) | Planner output: tasks, dependencies, tools, outline |
| [researcher-output.schema.json](../contracts/researcher-output.schema.json) | Evidence IDs used and unresolved questions per task |
| [writer-output.schema.json](../contracts/writer-output.schema.json) | Report: sections of typed claims with citations |
| [reviewer-output.schema.json](../contracts/reviewer-output.schema.json) | Findings (category, severity, claims) and outcome |
| [source.schema.json](../contracts/source.schema.json) | Retrieved source with provenance |
| [evidence-passage.schema.json](../contracts/evidence-passage.schema.json) | Stored passage with locator and hash |
| [approval-decision.schema.json](../contracts/approval-decision.schema.json) | Human decision bound to version and digest |
| [eval-case.schema.json](../contracts/eval-case.schema.json) | Evaluation case: brief, category, expectations |

## F. Configuration

Every setting is listed in the [README configuration table](../../README.md#configuration).

With `AOS_ENV=prod`, the application refuses to start unless all of the following hold:

- `AOS_DATABASE_URL` is set;
- `AOS_COOKIE_SECURE=true`;
- `AOS_OIDC_ISSUER` is an https URL that is not a local or dev issuer, and the dev client ID
  is not used;
- `AOS_PUBLIC_URL` uses https;
- a sign-in allowlist is set (`AOS_ALLOWED_EMAILS` and/or `AOS_ALLOWED_EMAIL_DOMAINS`);
- no test-only settings are present.

The Render values are in [render.yaml](../../render.yaml). The manual steps (secrets, the
identity provider and the first admin) are in
[deploy-render.md](../operations/deploy-render.md).

## G. Defects found during verification

Each of these was found by the project's own checks during M11–M15 and fixed with a test or a
recorded verification:

| Milestone | Defect | Fix |
| --- | --- | --- |
| M11 | A failed offline corpus search left an "uncertain" cost estimate for money that was never at stake | Offline providers are never priced (ADR 0017) |
| M11 | Deterministic agents draft from "contact sales" or marketing pages (dev-12/13) | Recorded as a limitation; needs semantic abstention (report §15) |
| M12 | An unreachable identity provider returned 400 | New `OidcUnavailable`, which returns 503 `identity_provider_unavailable` |
| M12 | FastAPI turned body-size errors into 400 | The middleware sends 413 itself before the body is parsed |
| M12 | The object-store directory was not writable by the non-root container user | Ownership set in the image; CI writes to it in `deploy-image` |
| M12 | OpenAPI docs exposed in production | Disabled when `AOS_ENV=prod` |
| M12 | `/readyz` did not check the schema version | Readiness requires the migration head |
| M12 | The worker could crash-loop on a database outage or before migrations | Capped backoff; waits for the schema head |
| M12 | Any account at a public identity provider could sign in | Required allowlist on the verified email, with audited denials |
| M14 | Windows memory measurement read the virtual-environment launcher, not the real process | Measured including child processes |
| M14 | Inconsistent percentile rounding in the load report | Single rounding rule |
| M15 | On phones, the stepper overflowed and the top bar wasted a row (found from screenshots) | Grid stepper and shrinking top bar below 640 px |
| M15 | Test helper could not mock 204 responses | `Response(null)` for 204 |
| M15 | Screenshot run raced the sign-out navigation (`ERR_ABORTED`) | Wait for `/signin` before navigating |

## H. Screenshots

Twelve screenshots of the real application, captured by `frontend/e2e/screenshots.spec.ts`
with the deterministic demo agents, are embedded in the [user guide](../user-guide.md). The
files are in [docs/assets/screenshots/](../assets/screenshots/):

| File | Shows |
| --- | --- |
| `01-sign-in.png` | Sign-in page |
| `02-new-brief.png` | Brief form with source policy and limits |
| `03-plan-awaiting-approval.png` | Plan v1 awaiting approval, bound to its digest |
| `04-report-with-review.png` | Report v2 awaiting approval, with review history |
| `05-flagged-claim-in-v1.png` | The planted unsupported claim highlighted in v1 |
| `06-evidence.png` | Evidence tab with provenance and hashes |
| `07-reviewer-checks-citation.png` | Reviewer opening the exact cited passage |
| `08-approved-report.png` | Approved report ready for clean export |
| `09-runs-list.png` | Runs list |
| `10-usage.png` | Usage and estimated cost |
| `11-activity-log.png` | Admin activity (audit) log |
| `12-mobile-run.png` | Run page at phone width |
