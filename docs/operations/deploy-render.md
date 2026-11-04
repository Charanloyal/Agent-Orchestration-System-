# Deploying to Render

Repository-side configuration is complete and checked in CI:

- the `deploy-image` job builds the root `Dockerfile`, migrates a real Postgres, starts web and
  worker with production settings, and probes the public surface;
- `render.yaml` is validated against Render's published Blueprint schema.

The steps below need a Render account, payment details (background workers are paid), and an
identity provider registration. Those are **manual**; nothing here has been deployed yet.

## What gets created

| Resource | Blueprint name | Type | Notes |
| --- | --- | --- | --- |
| API + web app | `aos-web` | Docker web service (paid) | Health check `/readyz`; pre-deploy `alembic upgrade head` |
| Workflow worker | `aos-worker` | Docker background worker (paid) | Same image, `python -m app.workers.runner` |
| Database | `aos-db` | Managed Postgres 17 | No public IPs allowed; services use the private connection string |

## 1. Register the app with an identity provider

Use any OpenID Connect provider that supports the authorization-code flow with PKCE and
returns a *verified* email claim, for example Google, Microsoft Entra ID, Auth0 or Okta.
**Never use the bundled dev issuer; production configuration refuses it.**

- **Redirect URI:** `https://<your-service>.onrender.com/api/v1/auth/callback`. Use the
  service's real URL; Render shows it after creation, and you can update the provider
  afterwards.
- **Scopes:** `openid email profile`.
- **Note down:** issuer URL (it must serve `/.well-known/openid-configuration`), client id and
  client secret.

## 2. Create the Blueprint

1. In the Render Dashboard, choose **New > Blueprint**, select this repository and branch
   `main`.
2. Render reads `render.yaml` and prompts for each `sync: false` variable:

| Variable | Value |
| --- | --- |
| `AOS_PUBLIC_URL` | `https://<your-service>.onrender.com` (no trailing slash) |
| `AOS_OIDC_ISSUER` | Your provider's issuer URL (https) |
| `AOS_OIDC_CLIENT_ID` / `AOS_OIDC_CLIENT_SECRET` | From step 1 (the worker needs only the id) |
| `AOS_ALLOWED_EMAILS` and/or `AOS_ALLOWED_EMAIL_DOMAINS` | Who may sign in, e.g. `you@uni.edu` or `uni.edu`. At least one is required |

   The web and worker services validate the same production settings. Enter identical values
   for both where prompted.
3. Apply. Render builds the image, runs `alembic upgrade head` as the web pre-deploy step,
   then starts both services. The worker waits until the schema is at head.

`AOS_METRICS_TOKEN` is generated automatically. Scrape `/metrics` with
`Authorization: Bearer <token>`.

## 3. Create the first workspace

1. Open `AOS_PUBLIC_URL` and sign in with an allowlisted account.
2. With no workspaces yet, create one through the API from the browser console on the site
   (CSRF token from `/api/v1/auth/me`):

   ```js
   const me = await (await fetch('/api/v1/auth/me')).json();
   await fetch('/api/v1/workspaces', {method: 'POST', headers: {'Content-Type': 'application/json',
     'X-CSRF-Token': me.csrf_token}, body: JSON.stringify({name: 'Pilot'})});
   ```

   The creator becomes the workspace admin. Add members (analyst, reviewer) with
   `POST /api/v1/workspaces/{id}/members` (`{"email", "role"}`); they must have signed in
   once.

`seed-demo` and its demo users are disabled in production by design.

## 4. Verify the deployment

Record each result; do not assume.

| # | Check | How |
| --- | --- | --- |
| 1 | Build and deploy succeeded | Render Deploys page shows "Live" for `aos-web` and `aos-worker` |
| 2 | Health | `curl -i https://<url>/healthz` → 200 |
| 3 | Readiness (DB + migration head) | `curl -i https://<url>/readyz` → 200 |
| 4 | Frontend loads, client routes refresh | Open `/` and `/runs/x` → the app shell |
| 5 | Production surface | `/api/openapi.json` → 404; `/api/v1/auth/me` without a cookie → 401; `/metrics` without the token → 401 |
| 6 | Sign-in | Allowlisted account signs in; another account sees "not invited" |
| 7 | Workflow | Submit a brief with `(demo: unsupported claim)` in the topic → approve the plan → report v2 after a review round → reviewer approves → export downloads as *approved* |
| 8 | Worker logs | `aos-worker` logs show `"worker started"`; no connection strings or secrets |
| 9 | Restart safety | Restart `aos-worker` during research. The run resumes; the timeline shows no duplicate tasks |
| 10 | Persistence | Redeploy `aos-web`; earlier runs and reports are still there (Postgres). Exports regenerate on demand |

## Rollback

- **Code:** in the Render Dashboard, open the service's Deploys page and redeploy an earlier
  successful deploy (Render keeps previous builds), or "Deploy a specific commit". Roll back
  `aos-worker` to the same commit.
- **Database:** migrations in this project are additive, so the previous release runs against
  the newer schema; rolling back code does not require a schema downgrade. If a downgrade is
  really needed, follow [migrations.md](migrations.md) (back up first; downgrade a copy first).
- **Failed migration:** a failing pre-deploy command fails the deploy, and the previous
  version keeps serving traffic.

## Known limitations of this deployment

- Paid instance types are required for the worker and the pre-deploy command.
- Free Postgres (if chosen instead) expires after 30 days.
- The object store is ephemeral, as described in ADR 0018: uploaded originals and export
  copies are lost on redeploy, while extracted text, evidence and reports are in Postgres.
- `AOS_AGENT_MODE=fake`: deterministic demo agents, not a real model. To use a model, set
  `AOS_AGENT_MODE=llm` and the `AOS_LLM_*` variables on **both** services, within an approved
  budget (ADR 0005).
- Single web instance assumed. Rate-limit and SSE state live in Postgres, so scaling out
  works, but it has not been load-tested on Render.
