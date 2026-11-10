# Troubleshooting

Problems you may hit when running, developing or demoing the system, and how to fix them. For
production incidents (provider outages, spend ceiling, secret exposure), use the
[incident runbook](operations/runbook.md) instead.

Every API error uses the same envelope, `{"error": {"code": "...", "message": "..."}}`, with
an `X-Request-ID` header. Search the JSON logs for that ID to find the server-side details.

## Starting up

| Symptom | Cause | Fix |
| --- | --- | --- |
| `GET /readyz` returns 503 `not_ready`, *"Database unavailable or not migrated"* | PostgreSQL is not running, or `AOS_DATABASE_URL` is wrong | Start PostgreSQL. Check the URL in `backend/.env`. |
| `GET /readyz` returns 503, *"...not at the expected migration head"* | Code is newer than the schema | `.\.venv\Scripts\python.exe -m alembic upgrade head` |
| Worker logs `database schema not compatible with this build; waiting` | The database is behind this build (no migration yet), or newer and no longer lists this build (ADR 0020) | Behind: run the migration (on Render, the pre-deploy step or start-up does this); the worker continues by itself. Newer: deploy a build at or after the database revision. `/readyz` gives the same reason. |
| Worker logs `database not reachable or not migrated; retrying` or `database unavailable; pausing` | Database outage | Nothing to do in the application; it backs off (up to 30 s) and resumes. Fix the database. |
| The API refuses to start: `unsafe production configuration: ...` | `AOS_ENV=prod` with a setting that is unsafe in production | Fix every item listed. Examples: an https `AOS_PUBLIC_URL` and a real https `AOS_OIDC_ISSUER`; `AOS_COOKIE_SECURE=true`; at least one address in `AOS_PLATFORM_ADMIN_EMAILS`; not `AOS_SIGNUP_MODE=open` with `AOS_AGENT_MODE=llm`. The bundled dev issuer is always refused in production. |
| Runs stay **Queued** | No worker is running | `.\.venv\Scripts\python.exe -m app.workers.runner` (from `backend`) |
| The sign-in page shows *"API unavailable"* | API not running on port 8000, or the Vite proxy cannot reach it | Start uvicorn (README step 2). With a corporate proxy, see the README section on proxies. |

## Signing in

| Symptom | Cause | Fix |
| --- | --- | --- |
| *"We couldn't reach …"* (`/signin?error=provider_unavailable`) | The OIDC issuer cannot be reached | Locally, start `python -m devtools.dev_oidc` (port 8001). In a deployment, check `AOS_OIDC_ISSUER` and outbound network access; the API log line `identity provider unavailable` has the detail. |
| *"This account doesn't have access yet"* / *"isn't invited yet"* (`not_allowed`) | The verified email is not a platform admin, not allowlisted, not on the access list and has no pending invitation | Invite it from **Settings**, approve its request on **Access**, or add it to the access list. The denial is audited without storing the email. |
| *"That sign-in attempt expired or was started in another tab"* (`login_expired`) | The attempt is older than 10 minutes, was already used, or the browser lacks the login cookie (`aos_login`, or `__Secure-aos_login` on https deployments; another browser, blocked cookies) | Start again from the same tab. Allow first-party cookies for the site. |
| *"We couldn't verify the response from …"* (`login_failed`) | Token exchange or ID-token verification failed | Check `AOS_OIDC_CLIENT_ID` / `AOS_OIDC_CLIENT_SECRET`, the redirect URI `<AOS_PUBLIC_URL>/api/v1/auth/callback` at the provider, and the server clock. |
| *"… did not confirm an email address"* (`email_unverified`) | The provider returned no email marked as verified (a missing `email_verified` counts as unverified) | Use an account with a verified email; check the `email` scope. With Microsoft Entra ID, add the `xms_edov` optional claim to the app registration. |
| *"Sign-in was cancelled …"* (`provider_denied`) or *"… reported a problem"* (`provider_error`) | The user cancelled, or the provider returned an error | Retry. Check the provider's client configuration. |
| *"Too many sign-in attempts …"* (`rate_limited`) | More than `AOS_RATE_LOGIN_PER_IP_5MIN` attempts from one address | Wait five minutes. If *everyone* on a deployment sees it at once, `AOS_TRUSTED_PROXY_HOPS` is too high and all visitors share one address ([ADR 0025](decisions/0025-client-address-behind-proxy.md)). |
| Signed in, but on the **Welcome** page | Signed in without a workspace membership | Create a workspace (if allowed), or ask a workspace admin to invite you. Locally, `python -m app.cli seed-demo`. |
| *"Your session ended"* | The session expired, was signed out elsewhere, or access was removed | Sign in again; you return to the same page. |
| *"Not permitted. Your role in this workspace can't …"* | The role lacks that permission | Ask a workspace admin to change your role. |
| *"This page is out of date"* (403 on an unsafe request) | Missing CSRF header or a cross-origin request | Reload. Scripts must send `X-CSRF-Token` with the `csrf_token` value from `GET /api/v1/auth/me`, and a matching `Origin`. |
| *"Only platform admins can create workspaces here"* | `AOS_WORKSPACE_CREATION=platform_admins` (the production default) | A platform admin creates the workspace and invites you as admin. |

## Using the application

| Message | Meaning |
| --- | --- |
| 409 *"The plan changed since you opened it; reload and edit the latest version"* | Someone else edited the plan. Reload. Decisions are bound to a version and digest by design. |
| 409 *"Only finished runs can be deleted; cancel the run first"* | Deletion is allowed only for terminal runs. |
| 409 *"Only failed runs can be retried"* or *"This failure cannot be retried"* | Retry applies only to `FAILED` runs, at most 3 times per run. Submit a new brief instead. |
| 409 *"Idempotency-Key was already used for a different request"* | A client reused a key with a different body. The web app generates a fresh key for each new brief. |
| 409 *"A workspace must keep at least one admin"* | Promote another admin first. |
| 413 `payload_too_large` | Uploads over 10 MB (`AOS_UPLOAD_MAX_BYTES`) or JSON bodies over 1 MB (`AOS_MAX_REQUEST_BYTES`). |
| 415 `unsupported_media_type` | Only text-based PDF, `.txt` and `.md` files are accepted. The type is detected from the content. |
| 422 `unreadable_document` | The file has no extractable text, for example a scanned PDF without OCR. |
| 429 `rate_limited` | Too many requests for this user or workspace. Wait for the `Retry-After` seconds. |
| A run is **Expired** | Nobody decided within `AOS_APPROVAL_TTL_HOURS` (72 h), or an automated segment passed the brief's deadline. Resubmit. |
| A run is **Failed** with `invalid model output after 2 attempts` | Live mode only: the model returned invalid JSON twice. Retry, or configure a stronger model. |

## Development and tests

| Symptom | Fix |
| --- | --- |
| Database tests are **skipped** | Set `AOS_TEST_DATABASE_URL` (a throwaway database; tests drop and rebuild it). |
| Playwright fails before any test | Set `AOS_E2E_DATABASE_URL` (also wiped). The suite uses ports 5180 (web), 8100 (API) and 8101 (identity provider). Stop anything already using them. |
| `test_contract_schemas` drift failure | You changed a contract. Run `python -m scripts.export_schemas` and commit the JSON. |
| Model/migration drift test fails | You changed a model. Run `alembic revision --autogenerate -m "..."`, review the migration, then commit it. |
| `&&` is rejected in PowerShell 5.1 | Use `;`, or `if ($?) { ... }`. |
| `pip`/`npm` cannot reach the registry behind a corporate proxy | See *Corporate proxies and package mirrors* in the [README](../README.md). |
| Ctrl+C on the worker seems slow | It finishes the current pass first (graceful stop measured at 0.6–0.7 s). A second Ctrl+C is not needed; an interrupted pass is resumed by the next claim. |

## Docker and Render

| Symptom | Fix |
| --- | --- |
| Uploads fail in the container with a permission error | Use the root `Dockerfile` image, where `/srv/data/objects` is owned by the non-root `aos` user (uid 10001). Mount any volume with the same ownership. |
| Render health check fails | `/readyz` must return 200 within 5 s. Usually the pre-deploy migration failed: read the deploy log. |
| A container shows **unhealthy** in Docker | Run `docker exec <container> python -m app.healthcheck`: it names the role that failed. A worker is unhealthy when its loop has not turned for two minutes: a stuck pass, or still waiting at start-up for the database or its migration; read its log. |
| Render worker restarts in a loop | It should wait, not crash. Check `AOS_DATABASE_URL` in the shared env group and the log lines above. |
| Uploaded files disappear after a Render redeploy | Render's filesystem is ephemeral. This is a documented pilot limitation; see [deploy-render.md](operations/deploy-render.md). |
