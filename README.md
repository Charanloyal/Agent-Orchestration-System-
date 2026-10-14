# Agent Orchestration System

A production-oriented research/reporting pilot. Planner, researcher, writer and reviewer
agents will be coordinated through one controlled, human-approved workflow.

> **Current state (Week 1 / Day 1):** local React-to-FastAPI health-check skeleton only.
> There is no database, authentication, workflow engine, model/search provider or agent
> code yet. This is a local development scaffold. **Do not deploy it as a secure product.**

## Repository layout

```text
backend/    FastAPI app (app/), pytest tests (tests/), pinned requirements
frontend/   React + TypeScript + Vite app that calls the backend through a dev proxy
docs/       Project documentation and architecture decision records
```

## Prerequisites

| Tool    | Version used for verification | Notes                                          |
| ------- | ----------------------------- | ---------------------------------------------- |
| Python  | 3.14.7                        | Other versions are untested.                   |
| Node.js | 24.21.0 LTS (npm 11.19.0)     | Vite 8 requires Node `^20.19.0 \|\| >=22.12.0`. |
| Git     | 2.55                          |                                                |

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

## Configuration and secrets

This milestone needs no secrets or environment variables. Never commit `.env` files,
credentials or keys. `.gitignore` excludes them, along with virtual environments,
`node_modules/` and build output.

## Documentation

See [docs/README.md](docs/README.md) for project status, decisions and the next milestone.
