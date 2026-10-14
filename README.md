# Agent Orchestration System

A production-oriented research/reporting pilot. Planner, researcher, writer and reviewer
agents will be coordinated through one controlled, human-approved workflow.

> **Current state (Week 2 complete):**
> - The local React-to-FastAPI health-check skeleton.
> - Typed workflow contracts with tests.
> - Week-1 planning documents and 20 development evaluation briefs.
> - A throwaway LangGraph + PostgreSQL persistence spike.
>
> There is still no application database, authentication, real model or search provider, or
> production agent code. This is a local development scaffold. **Do not deploy it as a
> secure product.**

## Repository layout

```text
backend/                 FastAPI app (app/), typed contracts (app/contracts/), tests, pinned requirements
frontend/                React + TypeScript + Vite app that calls the backend through a dev proxy
docs/                    Product, evaluation, security and architecture docs, ADRs, JSON Schemas
eval/briefs/dev/         20 development evaluation briefs (validated by backend tests)
spikes/week2_persistence Throwaway persistence/approval spike (LangGraph + PostgreSQL)
```

## Prerequisites

| Tool    | Version used for verification | Notes                                          |
| ------- | ----------------------------- | ---------------------------------------------- |
| Python  | 3.14.7                        | Other versions are untested.                   |
| Node.js | 24.21.0 LTS (npm 11.19.0)     | Vite 8 requires Node `^20.19.0 \|\| >=22.12.0`. |
| Git     | 2.55                          |                                                |
| PostgreSQL | 17.11                      | Only needed for the Week-2 spike. See below.   |

The commands below are for **Windows PowerShell**. macOS/Linux equivalents follow.

> **Windows note:** the default PowerShell execution policy (`Restricted`) blocks the
> `npm.ps1` shim. Use `npm.cmd`, as shown below, or run the commands from `cmd.exe`.

## Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Run tests
.\.venv\Scripts\python.exe -m pytest

# Start the API on http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Check it: open <http://127.0.0.1:8000/health>. It should return `{"status":"ok"}`.
Interactive API docs are at <http://127.0.0.1:8000/docs>.

### Contracts and JSON Schemas

Workflow contracts live in `backend/app/contracts/` (see
[ADR 0006](docs/decisions/0006-workflow-and-contracts.md)). Their JSON Schemas are checked in
under `docs/contracts/`. After changing a contract, regenerate the schemas; otherwise the
drift test fails:

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.export_schemas
```

## Frontend (React + Vite)

In a second terminal, with the backend still running:

```powershell
cd frontend
npm.cmd ci

# Start the dev server on http://127.0.0.1:5173
npm.cmd run dev
```

Open <http://127.0.0.1:5173>. The page calls `GET /health`. The Vite dev server proxies
that request to `http://127.0.0.1:8000`, and the page displays the real response. If the
backend is not running, the page shows an error (typically `HTTP 502`) and a
**Check again** button.

Production build (type-check plus bundle into `frontend/dist/`):

```powershell
npm.cmd run build
```

## macOS / Linux equivalents

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

cd ../frontend
npm ci
npm run dev
npm run build
```

## Corporate networks and package mirrors

`pip` and `npm` cannot authenticate to proxies that require Windows-integrated
(NTLM/Kerberos) authentication. If installs fail with `407 Proxy Authentication Required`,
point both tools at your organization's approved package mirror:

```powershell
.\.venv\Scripts\python.exe -m pip config --site set global.index-url <your-pypi-mirror-simple-url>
npm.cmd config set registry <your-npm-mirror-url>
```

`frontend/package-lock.json` records `https://registry.npmjs.org/` URLs. npm swaps that
host for the configured registry by default (`replace-registry-host=npmjs`), and the
integrity hashes are still verified.

## Local PostgreSQL (Week-2 spike only)

Any local PostgreSQL 17 works: an installer, Docker, or the portable binaries described here.
The spike was verified with the EnterpriseDB "binaries" zip, extracted into
`%LOCALAPPDATA%\Programs\postgresql-17`. No admin rights or Windows service are needed. EDB
publishes no checksum for that zip; see the
[threat model](docs/security/threat-model.md#local-development-notes-current-state).

```powershell
$bin  = "$env:LOCALAPPDATA\Programs\postgresql-17\pgsql\bin"
$data = "$env:LOCALAPPDATA\aos-pg\data"

# One-time setup: you will be prompted for a new superuser password.
& "$bin\initdb.exe" -D $data -U postgres --pwprompt --auth=scram-sha-256 --encoding=UTF8 --locale=C
Add-Content "$data\postgresql.conf" "`nlisten_addresses = '127.0.0.1'`nport = 54329`n"

# Start in a dedicated terminal (Ctrl+C stops it).
& "$bin\postgres.exe" -D $data

# In another terminal: create the spike database (prompts for the password).
& "$bin\psql.exe" -h 127.0.0.1 -p 54329 -U postgres -c "CREATE DATABASE aos_spike"
```

Then create `backend/.env`, which is git-ignored and must never be committed:

```text
AOS_DATABASE_URL=postgresql://postgres:<your-password>@127.0.0.1:54329/aos_spike
```

Spike setup and test commands are in
[spikes/week2_persistence/README.md](spikes/week2_persistence/README.md).

## Configuration and secrets

The only secret so far is the local database URL in `backend/.env`. Never commit `.env`
files, credentials or keys. `.gitignore` excludes them, along with virtual environments,
`node_modules/` and build output. Model and search providers are still **undecided**. All
code uses deterministic fake providers, and no paid calls are made
([ADR 0005](docs/decisions/0005-spending-ceiling.md)).

## Documentation

See [docs/README.md](docs/README.md) for project status, decisions and the next milestone.
