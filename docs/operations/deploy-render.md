# Deploying to Render

Repository-side configuration is complete and checked in CI:

- the `deploy-image` job builds the root `Dockerfile`, migrates a real Postgres, starts web and
  worker with production settings, and runs [`scripts/smoke_prod.py`](../../backend/scripts/smoke_prod.py)
  against the container. It then does the same for the single-service variant;
- `render.yaml` and `render.free.yaml` are validated against Render's published Blueprint
  schema.

Everything below needs the owner's accounts (Render, Google Cloud) and is **manual**. Record
each result in [rehearsals.md](rehearsals.md); do not assume.

## Choose a blueprint

| | `render.yaml` (recommended) | `render.free.yaml` |
| --- | --- | --- |
| Services | Web (API + SPA) and a separate background worker | One web service running API and worker (`python -m app.serve --migrate --with-worker`) |
| Migrations | Pre-deploy command `alembic upgrade head` | Run at start-up, before serving |
| Plans | Web `starter`, worker `starter`, Postgres `basic-256mb` (paid) | Web `free`, Postgres `free` |
| Limits | None beyond the plan | Sleeps when idle (slow first request; queued runs wait); the free database is time-limited by Render. Check Render's current free-tier terms |
| Rollback rehearsals | Supported | Supported (redeploy an earlier commit) |

Both run the deterministic demo agents (`AOS_AGENT_MODE=fake`) and are labelled as such in the
UI. Both use the access model in [ADR 0021](../decisions/0021-access-model.md) with
`AOS_SIGNUP_MODE=request`.

## 1. Register the app with Google (OpenID Connect)

Any OpenID Connect provider with the authorization-code flow and PKCE works (Microsoft Entra
ID, Auth0, Okta, Keycloak). These steps are for Google, which most pilot users already have.
**Never use the bundled dev issuer; production configuration refuses it.**

1. Open the Google Cloud console and create (or pick) a project for this deployment.
2. **APIs & Services > OAuth consent screen**:
   - User type **External**, app name "Agent Orchestration System", your support email;
   - scopes: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (nothing else);
   - while the app is in **Testing**, add every pilot user as a *test user*, or **publish** it.
     The basic scopes above need no Google verification.
3. **APIs & Services > Credentials > Create credentials > OAuth client ID**:
   - application type **Web application**;
   - authorized redirect URI: `https://<your-service>.onrender.com/api/v1/auth/callback`
     (Render shows the service URL after creation; you can add the URI then);
   - no JavaScript origins are needed.
4. Note the **client ID** and **client secret**. The issuer is `https://accounts.google.com`.
   The sign-in button then reads **"Continue with Google"** automatically (override it with
   `AOS_OIDC_PROVIDER_LABEL`).

Google returns `email_verified`; unverified addresses are never trusted. Google documents two
forms of the issuer claim, and both are accepted.

## 2. Create the Blueprint

1. In the Render Dashboard choose **New > Blueprint**, select this repository, branch `main`,
   and the blueprint file (`render.yaml` or `render.free.yaml`).
2. Render prompts for each `sync: false` variable:

| Variable | Value | Services |
| --- | --- | --- |
| `AOS_PUBLIC_URL` | `https://<your-service>.onrender.com` (no trailing slash) | web, worker |
| `AOS_OIDC_ISSUER` | `https://accounts.google.com` | web, worker |
| `AOS_OIDC_CLIENT_ID` | From step 1 | web, worker |
| `AOS_OIDC_CLIENT_SECRET` | From step 1 | web only |
| `AOS_PLATFORM_ADMIN_EMAILS` | Your own Google address, e.g. `you@gmail.com` (comma-separate several) | web, worker |

   The worker validates the same production settings as the web service: enter identical
   values where prompted.
3. Apply. With `render.yaml`, Render builds the image, runs `alembic upgrade head` as the web
   pre-deploy step, then starts both services; the worker waits until the schema is
   compatible. With `render.free.yaml`, the single service migrates on start.

`AOS_METRICS_TOKEN` is generated automatically; scrape `/metrics` with
`Authorization: Bearer <token>`.

### Variables changed in this release (for an existing Blueprint)

If a Blueprint was created from an earlier version of this repository:

| Change | Variable | Action |
| --- | --- | --- |
| **New, required** | `AOS_PLATFORM_ADMIN_EMAILS` | Add on web *and* worker before deploying; production refuses to start without it |
| New (blueprint group) | `AOS_SIGNUP_MODE=request` | Synced from the blueprint; set `invite` to accept invited people only |
| Now optional | `AOS_ALLOWED_EMAILS`, `AOS_ALLOWED_EMAIL_DOMAINS` | Keep or delete; people on them can always sign in. Keep `AOS_ALLOWED_EMAILS` set until rehearsal 2 is done: the 0009 build still requires an allowlist |
| Optional | `AOS_OIDC_PROVIDER_LABEL`, `AOS_WORKSPACE_CREATION`, `AOS_INVITATION_TTL_DAYS`, `AOS_RATE_ACCESS_REQUEST_PER_IP_HOUR`, `AOS_RETENTION_ACCESS_REQUEST_DAYS` | Defaults: derived label, `platform_admins`, 14, 5, 90 |

Migration 0010 copies every current workspace member onto the access list, so nobody who
already uses the deployment is locked out by the switch.

## 3. First sign-in and the first workspace

1. Open `AOS_PUBLIC_URL`, choose **Continue with Google**, and sign in with the platform admin
   address.
2. The welcome page offers **Create workspace** (only platform admins may, by default). You
   become its admin.
3. Invite people from **Settings > Invite people** (email and role). They join the first
   time they sign in with that address. No email is sent: tell them the URL.
4. Visitors who are not invited can **request access** on the sign-in page. Platform admins
   see the count next to **Access** in the top bar, and approve (optionally straight into a
   workspace with a role) or deny.

`seed-demo` and its demo users are disabled in production by design.

## 4. Verify the deployment

Run the automated part first, from any machine with Python 3:

```powershell
python backend/scripts/smoke_prod.py https://<url> --expect-signup-mode request --json smoke.json
```

It checks liveness, readiness, `/version`, security headers, the SPA and CSP, that the API
docs and metrics are not public, the auth config, the redirect to the provider with PKCE and
the right redirect URI, the login-binding cookie flags, friendly callback errors, and that a
cross-origin write is refused. It is read-only.

| # | Check | How | Result |
| --- | --- | --- | --- |
| 1 | Build and deploy succeeded | Render Deploys page shows "Live" (web and worker, or the single service) | |
| 2 | Automated checks | `smoke_prod.py` exits 0 (attach `smoke.json`) | |
| 3 | Serving the expected commit | `smoke_prod.py --expect-commit <sha>`, or `GET /version` | |
| 4 | Sign-in | The platform admin signs in with Google; an uninvited account sees the request form | |
| 5 | Access request | Request access from a second account; approve it into the workspace as analyst; that account signs in and lands in the workspace | |
| 6 | Invitation | Invite a third address as reviewer; it joins with that role on first sign-in | |
| 7 | Workflow | Submit a brief with `(demo: unsupported claim)` in the topic → approve the plan → report v2 after a review round → the reviewer approves → the export downloads as *approved* | |
| 8 | Worker logs | Logs show `"worker started"`; no connection strings or secrets | |
| 9 | Restart safety | Restart the worker (or the single service) during research; the run resumes and the timeline shows no duplicate tasks | |
| 10 | Persistence | Redeploy; earlier runs and reports are still there (Postgres). Exports regenerate on demand. Re-uploading a document restores its original if the disk was wiped | |
| 11 | Access removal | Remove the analyst from the access list; their open session ends at the next request | |

## 5. Rollback

Render keeps previous builds. To roll back code, open the service's **Deploys** page and use
**Rollback** on an earlier successful deploy (or **Manual Deploy > Deploy a specific
commit**). With `render.yaml`, roll back `aos-worker` to the same commit.

The **schema stays where it is**. From migration 0009 on, the database lists the code
revisions that may run against it ([ADR 0020](../decisions/0020-schema-compatibility-window.md)):
the previous build stays ready on the newer schema, and `/readyz` says so. A build that the
schema no longer supports reports not-ready with a clear message instead of failing at
runtime. Schema downgrades are a last resort: see [migrations.md](migrations.md) (back up
first, rehearse on a copy).

A failing pre-deploy migration fails the deploy, and the previous version keeps serving.
With `render.free.yaml`, a failing start-up migration keeps the new instance from becoming
healthy, and Render keeps the old one.

### Rehearsal 1: code-only rollback

1. Note the live commit (`GET /version`). Deploy a newer commit that adds no migration.
2. Roll back to the noted deploy. Run
   `smoke_prod.py <url> --expect-commit <noted sha>`; sign in; open an existing run.
3. Roll forward again and repeat. Record times and results in [rehearsals.md](rehearsals.md).

### Rehearsal 2: rollback across the access-model migration (0010)

This proves the compatibility window. It needs the deployment to have run a build at
migration **0009** first. That is the first commit of this release, "Sign-in hardening,
schema compatibility window and deploy tooling" (`git log --oneline`). The 0009 build predates
the access model: it requires `AOS_ALLOWED_EMAILS` (set it to your own address on both
services) and ignores `AOS_PLATFORM_ADMIN_EMAILS`. Keep both set for the whole rehearsal.

1. Deploy the 0009 build. `GET /version` shows `migration_head: "0009"`; `smoke_prod.py`
   passes; sign in and create a run.
2. Deploy the current build (0010). Migration 0010 runs; `/version` shows `"0010"`; record
   the smoke result, then submit and approve a plan.
3. **Roll back** to the 0009 deploy. Expected: the deploy goes live (readiness passes on the
   0010 schema); `smoke_prod.py --expect-commit <0009 sha>` passes; existing runs open; the
   worker logs `"worker started"`, not "schema not compatible". The access-model pages are
   absent in this build, but sign-in works for allowlisted people.
4. Roll forward to the current build. Expected: no migration runs (already at 0010); the data
   created in steps 2-3 is intact; access requests and invitations work again.
5. Record each step with time, commit, `/version` output and smoke result in
   [rehearsals.md](rehearsals.md).

## Known limitations of this deployment

- `render.yaml` needs paid instance types for the worker and the pre-deploy command;
  `render.free.yaml` trades that for sleeping and a time-limited database.
- The object store is the container's ephemeral disk ([ADR 0022](../decisions/0022-deployment-variants-ephemeral-storage.md)):
  uploaded originals and export copies are lost on redeploy or restart. Extracted text,
  evidence, reports and approvals are in Postgres, so nothing a report depends on is lost;
  re-uploading a file restores its original. Attach a persistent disk or an S3-compatible
  store before a pilot that needs the originals.
- `AOS_AGENT_MODE=fake`: deterministic demo agents, not a real model. To use a model, set
  `AOS_AGENT_MODE=llm` and the `AOS_LLM_*` variables on **both** services, within an approved
  budget (ADR 0005). Production refuses `AOS_SIGNUP_MODE=open` with model agents.
- A single web instance is assumed. Rate-limit and SSE state live in Postgres, so scaling out
  works, but it has not been load-tested on Render.
