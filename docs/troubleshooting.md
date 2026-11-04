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
| Worker logs `database schema not at migration head; waiting` | Same: the worker never migrates; it waits for the API's migration step | Run the migration (on Render, the web service's pre-deploy command does this). The worker continues by itself. |
| Worker logs `database not reachable or not migrated; retrying` or `database unavailable; pausing` | Database outage | Nothing to do in the application; it backs off (up to 30 s) and resumes. Fix the database. |
| The API refuses to start: `unsafe production configuration: ...` | `AOS_ENV=prod` with a setting that is unsafe in production | Fix every item listed. Examples: an https `AOS_PUBLIC_URL` and a real https `AOS_OIDC_ISSUER`; `AOS_COOKIE_SECURE=true`; an allowlist via `AOS_ALLOWED_EMAILS` or `AOS_ALLOWED_EMAIL_DOMAINS`. The bundled dev issuer is always refused in production. |
| Runs stay **Queued** | No worker is running | `.\.venv\Scripts\python.exe -m app.workers.runner` (from `backend`) |
| The sign-in page shows *"API unavailable"* | API not running on port 8000, or the Vite proxy cannot reach it | Start uvicorn (README step 2). With a corporate proxy, see the README section on proxies. |

## Signing in

| Symptom | Cause | Fix |
| --- | --- | --- |
| 503 `identity_provider_unavailable` | The OIDC issuer cannot be reached | Locally, start `python -m devtools.dev_oidc` (port 8001). In a deployment, check `AOS_OIDC_ISSUER` and outbound network access. |
| *"Your account is not invited to this deployment"* | Email not on the allowlist | Add the address to `AOS_ALLOWED_EMAILS`, or its domain to `AOS_ALLOWED_EMAIL_DOMAINS`, then restart. The denial is audited without storing the email. |
| *"Sign-in was cancelled or denied by the identity provider"* | The user cancelled at the provider, or it returned an error | Retry. Check the provider's client configuration and that its redirect URI is `<AOS_PUBLIC_URL>/api/v1/auth/callback`. |
| Signed in, but *"not a member of any workspace yet"* | Sign-in creates a user, not a membership | An admin adds the user to a workspace (or run `python -m app.cli seed-demo` locally). |
| 403 `forbidden` on an unsafe request | Missing CSRF header or a cross-origin request | Use the web app (it sends the header automatically). Scripts must send `X-CSRF-Token` with the `csrf_token` value from `GET /api/v1/auth/me`, and a matching `Origin`. |

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
| Render worker restarts in a loop | It should wait, not crash. Check `AOS_DATABASE_URL` in the shared env group and the log lines above. |
| Uploaded files disappear after a Render redeploy | Render's filesystem is ephemeral. This is a documented pilot limitation; see [deploy-render.md](operations/deploy-render.md). |
