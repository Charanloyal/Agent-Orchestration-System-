# 0001: Local health-check scaffold

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

The repository started empty. The first milestone is the smallest runnable vertical slice:
a React page that displays the real response from a FastAPI health endpoint. It must not
pull in target-architecture dependencies (database, auth, LangGraph, providers, Docker)
before they are needed.

## Decisions

1. **Same-origin dev proxy instead of CORS.** Vite proxies `/health` to
   `http://127.0.0.1:8000`, so the backend needs no CORS configuration. When more
   endpoints arrive, a shared API path prefix (for example `/api/v1`) will be decided
   in a separate ADR.
2. **Exact version pins.** Direct dependencies are pinned exactly in
   `backend/requirements*.txt` and `frontend/package.json`. The frontend also commits
   `package-lock.json`. Versions were resolved on 2026-10-14 and verified together:
   FastAPI 0.143.0, Uvicorn 0.54.0, pytest 9.1.1, httpx2 2.13.1, React 19.3.0, Vite 8.3.4,
   @vitejs/plugin-react 6.1.2 and TypeScript 7.0.2.
3. **`httpx2` for tests.** The installed Starlette `TestClient` prefers `httpx2` and emits
   a deprecation warning when it falls back to `httpx`. pytest treats warnings as errors.
4. **Liveness-only `/health`.** It reports that the process is serving. Readiness checks
   (database, object storage) will be added when those dependencies exist.
5. **Localhost binding.** Both dev servers bind to `127.0.0.1` only.

## Consequences

- There is no backend lockfile for transitive Python dependencies yet. Adopt a lock
  workflow (for example `pip-tools`) before CI is added.
- TypeScript 7 (native compiler) and Vite 8 are recent major versions. Tooling that
  depends on the TypeScript JavaScript API may need checking when added.
