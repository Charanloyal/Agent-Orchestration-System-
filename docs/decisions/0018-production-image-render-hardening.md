# 0018: Single-origin production image, Render topology and production hardening

- **Status:** Accepted; amended by [0020](0020-schema-compatibility-window.md) (readiness
  accepts a compatible newer schema), [0021](0021-access-model.md) (platform admins replace
  the required allowlist) and [0022](0022-deployment-variants-ephemeral-storage.md)
  (free single-service variant, storage behaviour)
- **Date:** 2026-11-03
- **Requirements:** PRD week 12 (controlled pilot), NFR security; threat model T3, T10, T11,
  T15; ADR 0004 (deployment target), ADR 0009 (identity)

## Context

The local stack (docker-compose) uses nginx in front of the API and a bundled dev OIDC issuer.
A hosted pilot on Render needs three things:

- **The minimum service topology that preserves behaviour:** leased background work, human
  gates, SSE.
- **A deploy that cannot accidentally run development defaults:** the dev issuer, insecure
  cookies, an open sign-up.
- **Health checks** that only route traffic to instances whose database schema matches the
  code.

## Decisions

1. **One image, two processes** (`Dockerfile` at the repository root).
   - A Node stage builds the SPA. The Python stage serves it from the API (`AOS_STATIC_DIR`)
     on the same origin as `/api`, so there is no CORS, cookies stay first-party, and no
     second web service or nginx is needed. Unknown non-API paths return `index.html` (client
     routing survives refresh); unknown `/api` paths keep the JSON 404 envelope.
   - HTML responses carry the same CSP as the nginx front end. Hashed assets are cached as
     immutable.
   - The same image runs the worker (`python -m app.workers.runner`). The worker is a separate
     process and service: never threads inside the API.
   - `backend/devtools` (the dev OIDC issuer), tests, evaluation code and docs are excluded
     from the image.
2. **Render topology** (`render.yaml`, validated against Render's published Blueprint schema
   in CI):
   - Docker web service `aos-web`: health check `/readyz`, `preDeployCommand: alembic upgrade
     head`, binds `0.0.0.0:$PORT`.
   - Docker background worker `aos-worker`.
   - Managed Postgres 17 `aos-db`, with no public IP allow-list; services use the private
     connection string.
   - Render's docs state that background workers and pre-deploy commands need paid instance
     types, so this blueprint is not free-tier. Free Postgres instances expire after 30 days.
   - Secrets are `sync: false` or `generateValue`; nothing secret is committed.
3. **Readiness means "schema at head".** `/readyz` compares `alembic_version` with the code's
   head revision, so a deploy whose migration did not run never receives traffic. Liveness
   (`/healthz`) does not touch the database.
   - The image's Docker `HEALTHCHECK` (`python -m app.healthcheck`, finding G4) fits each role:
     a web server must answer `/healthz`; a worker, which serves no HTTP, must have touched
     `AOS_WORKER_ALIVE_FILE` within two minutes (every loop turn and every lease extension);
     the single-process command must pass both. Render itself uses `/readyz` for web services;
     the Docker check serves other runtimes and CI, which asserts each role is healthy.
   - The worker waits, with capped backoff, until the schema is at head before polling. Web
     and worker deploy independently, and the migration runs only in the web service's
     pre-deploy step.
   - The worker's poll loop pauses on database outages instead of exiting.
4. **Production refuses unsafe configuration at start-up** (`Settings._production_safety`).
   With `AOS_ENV=prod`, the process exits with a message naming every variable to fix if any
   of these hold:
   - no database URL;
   - non-secure cookies;
   - a non-https or local issuer, or the dev client id `aos-local`;
   - a non-https public URL;
   - no sign-in allowlist;
   - fault injection enabled.

   The dev issuer itself also refuses `AOS_ENV=prod`.
5. **Sign-in allowlist** (`AOS_ALLOWED_EMAILS`, `AOS_ALLOWED_EMAIL_DOMAINS`, required in prod;
   since ADR 0021 optional, with `AOS_PLATFORM_ADMIN_EMAILS` required instead).
   It matches the provider's *verified* email. Uninvited accounts get no user row and no
   session; the refusal is audited without storing the address. Without this, anyone with an
   account at a public identity provider could create workspaces and runs.
6. **Edge limits and surface.**
   - JSON request bodies are capped at `AOS_MAX_REQUEST_BYTES` (1 MB), uploads at the upload
     limit plus 1 MB. Streamed bodies are counted, and the response is 413 with the error
     envelope.
   - OpenAPI JSON and interactive docs are disabled in prod.
   - An unreachable identity provider is a 503 naming `AOS_OIDC_ISSUER`, not a 400.

## Consequences

- **Ephemeral filesystem.** Render's filesystem is ephemeral and per service. Since
  [ADR 0026](0026-no-file-copies-on-render.md) the blueprints keep no file copies at all
  (`AOS_STORE_FILES=false`): everything the workflow reads (extracted upload chunks, evidence,
  reports, findings, approvals) is in Postgres, and exports are rendered on every download.
  Serving originals back would need an S3-compatible store.
- **Fake agents by default.** The hosted demo runs the deterministic fake agents
  (`AOS_AGENT_MODE=fake`) and is labelled as such. It demonstrates the workflow, not
  real-model quality.
- **No public authenticated deployment yet.** A real identity provider registration (client
  id, secret, redirect URI) is a manual step; see
  [deploy-render.md](../operations/deploy-render.md).
- **Proxy headers.** Superseded by [ADR 0025](0025-client-address-behind-proxy.md): uvicorn no
  longer trusts forwarded headers; the app reads `X-Forwarded-For` only as far as
  `AOS_TRUSTED_PROXY_HOPS` allows.
