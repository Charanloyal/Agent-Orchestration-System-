# Documentation

## Status

| Milestone                                         | State                                                      |
| ------------------------------------------------- | ---------------------------------------------------------- |
| Week 1 / Day 1: local health-check skeleton       | Done: backend test passes, frontend builds, browser verified |
| Week 1: scope and evaluation planning             | Not started                                                |
| Week 2: persistence and approval spikes           | Not started                                                |

### Implemented behavior

- `GET /health` (FastAPI) returns `200 {"status": "ok"}`. This is a liveness check only;
  it does not check dependencies yet.
- The React page fetches `/health` through the Vite dev proxy. It shows loading, success
  (the actual response body) and error states, plus a retry button.

### Not implemented (target architecture only)

Database/Alembic, authentication/authorization, LangGraph, workers and job leases, agents,
model/search providers, object storage, observability, Docker and CI.

### Open decisions

Model provider, search provider, deployment target and development spending ceiling are
all **UNDECIDED**.

## Architecture decision records

- [0001: Local health-check scaffold](decisions/0001-local-health-check-scaffold.md)
