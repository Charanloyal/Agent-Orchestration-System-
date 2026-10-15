# Agent Orchestration System

Evidence-backed research and report generation, with reliable multi-agent execution and
human approval. Planner, researcher, writer and reviewer agents are coordinated by one
controlled workflow:

brief → typed plan → **human plan approval** → bounded parallel research → cited draft →
structured review (at most 2 rounds) → **human approval of the exact report version** →
export.

> **Status:** controlled-pilot build in progress. See [docs/README.md](docs/README.md) for
> milestone status and [docs/handoff.md](docs/handoff.md) for the verified state. This is
> a local, production-like pilot. **Do not expose it publicly**: the bundled dev identity
> provider is for local use only.

## Repository layout

```text
backend/                  FastAPI API, workers, agents, contracts, Alembic migrations, tests
backend/devtools/         Local dev OIDC issuer (never used in prod)
frontend/                 React + TypeScript + Vite single-page app (same-origin API proxy)
docs/                     Product, evaluation, security and architecture docs; ADRs; JSON Schemas
eval/                     Evaluation briefs (dev set; held-out procedure)
spikes/week2_persistence/ Archived Week-2 spike (evidence for ADR 0007/0008)
docker-compose.yml        Local production-like stack (Postgres, API, dev IdP, web)
.github/workflows/ci.yml  Lint, type-check, tests on Postgres, frontend build, image builds
```

## Prerequisites

| Tool | Version verified | Notes |
| --- | --- | --- |
| Python | 3.14.7 | |
| Node.js | 24.21.0 LTS (npm 11.19.0) | Vite 8 needs Node `^20.19.0 \|\| >=22.12.0` |
| PostgreSQL | 17.11 | Native install, portable zip, or Docker |
| Docker (optional) | Compose v2 | Only for `docker compose up` |

Commands are for **Windows PowerShell**; macOS/Linux equivalents are at the end.

> **Windows:** the default execution policy blocks `npm.ps1`, so use `npm.cmd`.

## 1. Database

Any PostgreSQL 17 works. With the portable EnterpriseDB zip extracted to
`%LOCALAPPDATA%\Programs\postgresql-17` (no admin rights or Windows service needed; see the
[threat model](docs/security/threat-model.md#local-development-notes-current-state) about
binary verification):

```powershell
$bin  = "$env:LOCALAPPDATA\Programs\postgresql-17\pgsql\bin"
$data = "$env:LOCALAPPDATA\aos-pg\data"
& "$bin\initdb.exe" -D $data -U postgres --pwprompt --auth=scram-sha-256 --encoding=UTF8 --locale=C
Add-Content "$data\postgresql.conf" "`nlisten_addresses = '127.0.0.1'`nport = 54329`n"
& "$bin\postgres.exe" -D $data                      # keep running in its own terminal
& "$bin\psql.exe" -h 127.0.0.1 -p 54329 -U postgres -c "CREATE DATABASE aos" -c "CREATE DATABASE aos_test"
```

Create `backend/.env`. It is **git-ignored; never commit it**.

```text
AOS_DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:54329/aos
AOS_TEST_DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:54329/aos_test
```

## 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head          # create/upgrade the schema
.\.venv\Scripts\python.exe -m app.cli seed-demo             # demo workspaces + users (dev only)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal, start the **local dev identity provider** (sign-in for the demo users
Alice/analyst, Bob/reviewer, Carol/admin and Mallory/other workspace):

```powershell
cd backend
.\.venv\Scripts\python.exe -m devtools.dev_oidc             # http://127.0.0.1:8001
```

In a third terminal, start a **workflow worker**. Add more workers for parallelism; they
coordinate through PostgreSQL leases.

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.workers.runner
```

Agents are deterministic fakes by default (`AOS_AGENT_MODE=fake`), so the whole workflow runs
without any model provider or cost.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Liveness |
| `GET /readyz` | Readiness (database reachable and migrated) |
| `GET /api/docs` | Interactive OpenAPI docs (disabled in prod) |
| `GET /api/v1/auth/login` | Start OIDC sign-in |

**Checks** (the same commands CI runs):

```powershell
.\.venv\Scripts\python.exe -m ruff check app devtools tests scripts migrations\env.py
.\.venv\Scripts\python.exe -m ruff format --check app devtools tests scripts migrations\env.py
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q
```

Database tests use `AOS_TEST_DATABASE_URL`. That database is **dropped and rebuilt** by the
tests, so never point it at real data. Without it, database tests are skipped, not passed.

After changing a contract in `app/contracts/`, regenerate the checked-in JSON Schemas:
`.\.venv\Scripts\python.exe -m scripts.export_schemas`. A drift test enforces this.

After changing a model in `app/db/models/`, create a migration with
`.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "<what changed>"` and
review it. A test fails if the models and migrations differ.

## 3. Frontend

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev        # http://127.0.0.1:5173 (proxies /api to the backend)
npm.cmd run typecheck  # app + end-to-end test sources
npm.cmd test           # Vitest unit tests
npm.cmd run build      # production bundle
```

Open <http://127.0.0.1:5173> and sign in as Alice to submit a brief. Approve the plan as
Alice, then sign in as Bob to review the cited report and approve it.

### End-to-end tests (Playwright)

The E2E suite starts an **isolated stack** (dev IdP on 8101, API on 8100, a worker, Vite on
5180) against a dedicated database, which it **wipes and re-seeds**. Add it to `backend/.env`:

```text
AOS_E2E_DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:54329/aos_e2e
```

```powershell
npm.cmd run e2e        # uses installed Microsoft Edge locally; CI uses Playwright's Chromium
```

## 4. Docker Compose (optional, production-like)

```powershell
Copy-Item .env.example .env        # set POSTGRES_PASSWORD; .env is git-ignored
docker compose up --build          # http://localhost:8080 , dev IdP on http://localhost:8001
```

Both ports bind to 127.0.0.1 only. CI builds these images on every push.

## Configuration

All settings are environment variables prefixed with `AOS_`, defined in
[backend/app/config.py](backend/app/config.py). Secrets are typed `SecretStr` and never
logged. `AOS_ENV=prod` enforces secure cookies and HTTPS URLs for the public site and the
issuer.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AOS_DATABASE_URL` | none | PostgreSQL URL |
| `AOS_PUBLIC_URL` | `http://127.0.0.1:5173` | Browser-facing origin (CSRF Origin check, OIDC redirect) |
| `AOS_OIDC_ISSUER` | `http://127.0.0.1:8001` | OIDC issuer (dev issuer by default) |
| `AOS_OIDC_CLIENT_ID` / `AOS_OIDC_CLIENT_SECRET` | `aos-local` / none | Client registration (the secret is for Google or Entra) |
| `AOS_OIDC_BACKCHANNEL_URL` | none | Internal issuer URL for server-to-server calls |
| `AOS_COOKIE_SECURE` | `false` | Must be `true` in prod |
| `AOS_AGENT_MODE` | `fake` | `fake` (deterministic, free) or `llm` (real model; see "Live model" below) |
| `AOS_SEARCH_PROVIDER` | `fake` | `fake`, `corpus` (offline, versioned, free) or `tavily` (live; needs `AOS_TAVILY_API_KEY`) |
| `AOS_TAVILY_API_KEY` | none | Tavily key (secret; `.env` only) |
| `AOS_OBJECT_STORE_DIR` | `backend/.data/objects` | Local object storage for uploads (git-ignored) |
| `AOS_UPLOAD_MAX_BYTES` / `AOS_FETCH_MAX_BYTES` | 10 MB / 2 MB | Upload and fetched-page size limits |
| `AOS_WORKER_LEASE_SECONDS` / `AOS_WORKER_HEARTBEAT_SECONDS` | `30` / `10` | Job lease and heartbeat |
| `AOS_JOB_MAX_ATTEMPTS` | `5` | Transient-retry budget per segment |
| `AOS_APPROVAL_TTL_HOURS` | `72` | How long a plan or report waits for a human |

## Live model and search (optional, costs money)

Everything runs on deterministic fakes by default. To use a real model, add the settings to
`backend/.env`. The project ceiling is **USD 10** ([ADR 0005](docs/decisions/0005-spending-ceiling.md)).

```text
AOS_AGENT_MODE=llm
# OpenAI:
AOS_LLM_API_KEY=<key>
AOS_LLM_MODEL=gpt-4o-mini
# ...or Groq: AOS_LLM_BASE_URL=https://api.groq.com/openai/v1 and a Groq model name
# ...or local Ollama (free): AOS_LLM_BASE_URL=http://127.0.0.1:11434/v1, AOS_LLM_MODEL=llama3.1
# ...or Azure OpenAI: AOS_LLM_API_STYLE=azure, AOS_LLM_AZURE_ENDPOINT=..., AOS_LLM_MODEL=<deployment>
AOS_SEARCH_PROVIDER=tavily
AOS_TAVILY_API_KEY=<key>
```

Opt-in live smoke test (one small planner call): `$env:AOS_LIVE_TESTS="1"; .\.venv\Scripts\python.exe -m pytest -m live -s tests/live`.

## Corporate proxies and package mirrors

`pip` and `npm` cannot authenticate to NTLM/Kerberos proxies. If installs fail with
`407 Proxy Authentication Required`, use your organization's package mirror:

```powershell
.\.venv\Scripts\python.exe -m pip config --site set global.index-url <pypi-mirror-simple-url>
npm.cmd config set registry <npm-mirror-url>
```

## macOS / Linux

Replace `.\.venv\Scripts\python.exe` with `.venv/bin/python` and `npm.cmd` with `npm`.

## Documentation

[docs/README.md](docs/README.md) indexes the product brief, evaluation plan, threat model,
architecture and all decision records.
