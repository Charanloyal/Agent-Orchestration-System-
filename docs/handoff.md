# Session handoff

Uses the template from the context prompt (§4). Contains no secrets or private source content.

```text
Project: Agent Orchestration System
Current milestone: M12 (controlled pilot and deployment packaging) and M13 (retention,
  deletion, audit): DONE on the repository side. Next: M14 load testing and recovery drills,
  M15 UX/accessibility, M16 final report.

Last completed vertical slice:
  The root Dockerfile builds one image: the API serves the SPA on the same origin, the same
  image runs the worker, and the dev issuer is excluded. render.yaml defines web + worker +
  managed Postgres (validated against Render's Blueprint schema). Production refuses unsafe
  settings and needs a sign-in allowlist. /readyz requires the schema at migration head, and
  the worker waits for migrations and survives database outages. Admins can delete finished
  runs (including checkpoints and export files); a retention sweep runs; audit events are
  append-only. `seed-demo --sample-run` plus docs/demo/demo-script.md reproduce the demo.

Architecture decisions accepted:
  0001–0017 as before; 0018 single-origin image, Render topology, production hardening;
  0019 data lifecycle and append-only audit log.

Database migrations:
  0001 … 0008 (0008: audit_events append-only trigger). Dev DB `aos` at 0008.

Tests actually run (Windows, Python 3.14.7, PostgreSQL 17.11, Node 24.21): see the latest
  commit message and the README checks. A prod-like local run (AOS_ENV=prod, SPA served by
  the API, separate worker, isolated database aos_prodlike) verified: readyz 200,
  openapi/docs/metrics 404, /me 401, client routes return the app, immutable asset caching,
  413 for a 1.5 MB body, worker waits for migrations, no secrets in logs.

Checks not run:
  Docker builds (no Docker locally; CI `containers` and `deploy-image` jobs build and
  smoke-test them). Render deployment (no account access; manual steps in
  docs/operations/deploy-render.md). Live-model evaluation (needs a key and a budget).

Known gaps:
  M14 load test and backup/restore drill; M15 UI polish, accessibility, screenshots, user
  guide; M16 final report. Live evaluation and human scoring need the project lead.
```