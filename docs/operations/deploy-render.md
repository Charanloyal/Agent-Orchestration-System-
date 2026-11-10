# Deploying to Render

Repository-side configuration is checked in CI on every pull request (job `deploy-image`,
[ADR 0023](../decisions/0023-deploy-topologies-and-ci-proof.md)):

- every `render*.yaml` is validated against Render's published Blueprint schema, and
  [`scripts/check_blueprints.py`](../../backend/scripts/check_blueprints.py) checks that each
  one starts the image the way the job does;
- the job builds the root `Dockerfile` and starts each topology with production settings
  against a real Postgres, then runs [`scripts/smoke_prod.py`](../../backend/scripts/smoke_prod.py):
  web plus a separate worker (started without any sign-in settings), and the single process
  of the hybrid and free blueprints, which migrates a fresh database on start;
- the build just before the newest migration is started on the new schema and must be ready,
  pass the smoke test and start its worker ([ADR 0020](../decisions/0020-schema-compatibility-window.md)).

Everything below needs the owner's accounts (Render, Google Cloud) and is **manual**. Record
each result in [rehearsals.md](rehearsals.md); do not assume.

## Choose a blueprint

| | `render.hybrid.yaml` (chosen) | `render.yaml` | `render.free.yaml` |
| --- | --- | --- | --- |
| Services | One web service running API and worker (`python -m app.serve --migrate --with-worker`) | Web (API + SPA) and a separate background worker | As hybrid |
| Migrations | Run at start-up, before serving | Pre-deploy command `alembic upgrade head` | As hybrid |
| Plans | Web `free`, Postgres `basic-256mb` (paid) | Web `starter`, worker `starter`, Postgres `basic-256mb` (paid) | Web `free`, Postgres `free` |
| Limits | Sleeps after 15 idle minutes (slow first request; queued runs wait until it wakes); the database does not expire | None beyond the plans | As hybrid, and Render deletes free databases after 30 days (check Render's current terms) |
| Rollback rehearsals | Supported (redeploy an earlier commit) | Supported | Supported |
| Database connections, worst case | 43 (pools 5 + 5) | 83 (pools 10 + 10) | 43 (pools 5 + 5) |

All three run the deterministic demo agents (`AOS_AGENT_MODE=fake`) and are labelled as such
in the UI. All use the access model in [ADR 0021](../decisions/0021-access-model.md) with
`AOS_SIGNUP_MODE=request`, and all are in the `singapore` region. Render cannot move a
service or database to another region after creation.

**Database connections.** Render Postgres plans below 8 GB of RAM (including `basic-256mb`
and `free`) accept at most **100** connections. Each process has one SQLAlchemy pool of
`AOS_DB_POOL_SIZE + AOS_DB_MAX_OVERFLOW` connections (defaults 10 + 10); a worker adds one for
the workflow checkpointer, and the migration uses one. During a deploy the old and new
instances run side by side, so the worst case is
`2 × (web pool + worker pool + 1) + 1`. `scripts/check_blueprints.py` computes it for each
blueprint and fails CI above 90, keeping room for `psql` and Render's own connections. A
second worker, or larger pools, must fit in that budget.

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

Google returns `email_verified`; only `true` is trusted, and a token without it counts as
unverified ([ADR 0024](../decisions/0024-verified-email-only.md)). Google documents two forms of
the issuer claim, and both are accepted. With Microsoft Entra ID instead, add the optional ID
token claim `xms_edov` in the app registration and prefer a single-tenant issuer; without it,
Entra accounts end on "did not confirm an email address". Auth0 issuers end in a slash
(`https://<tenant>.auth0.com/`); enter it with or without the slash, because ID tokens are
checked against the exact issuer the provider's discovery document names.

## 2. Create the Blueprint

1. In the Render Dashboard choose **New > Blueprint**, select this repository, branch `main`,
   and the blueprint file (`render.hybrid.yaml`, `render.yaml` or `render.free.yaml`).
2. Render prompts for each `sync: false` variable:

| Variable | Value | Services |
| --- | --- | --- |
| `AOS_OIDC_ISSUER` | `https://accounts.google.com` | web |
| `AOS_OIDC_CLIENT_ID` | From step 1 | web |
| `AOS_OIDC_CLIENT_SECRET` | From step 1 | web |
| `AOS_PLATFORM_ADMIN_EMAILS` | Your own Google address (comma-separate several) | web |

   The public URL is taken from Render's `RENDER_EXTERNAL_URL`, so there is nothing to type
   for it. Set `AOS_PUBLIC_URL` (no trailing slash) on the web service only for a custom
   domain, and register that domain's callback URI at Google too.
   The separate worker of `render.yaml` serves no HTTP and needs none of these (ADR 0023).
3. Apply. With `render.yaml`, Render builds the image, runs `alembic upgrade head` as the web
   pre-deploy step, then starts both services; the worker waits until the schema is
   compatible. With `render.hybrid.yaml` or `render.free.yaml`, the single service migrates
   on start.

`AOS_METRICS_TOKEN` is generated automatically; scrape `/metrics` with
`Authorization: Bearer <token>`.

### Variables changed in this release (for an existing Blueprint)

If a Blueprint was created from an earlier version of this repository:

| Change | Variable | Action |
| --- | --- | --- |
| **New, required** | `AOS_PLATFORM_ADMIN_EMAILS` | Add on the web service before deploying; production refuses to start without it |
| No longer needed on the worker | `AOS_PUBLIC_URL`, `AOS_OIDC_ISSUER`, `AOS_OIDC_CLIENT_ID`, `AOS_PLATFORM_ADMIN_EMAILS` | May be deleted from `aos-worker`; it ignores them |
| New (blueprint group) | `AOS_SIGNUP_MODE=request` | Synced from the blueprint; set `invite` to accept invited people only |
| **Changed (blueprint group)** | `AOS_RETENTION_RUN_DAYS=0`, `AOS_RETENTION_UPLOAD_DAYS=0` | Synced from the blueprint; runs and uploads are kept until deleted (were 30 days) |
| Behaviour change, no variable | Session cookie renamed to `__Host-aos_session` (login cookie `__Secure-aos_login`); HSTS, COOP and Permissions-Policy headers | Everyone signed in before the deploy signs in once more; the old `aos_session` cookie expires on its own |
| Now optional | `AOS_ALLOWED_EMAILS`, `AOS_ALLOWED_EMAIL_DOMAINS` | Keep or delete; people on them can always sign in. Keep `AOS_ALLOWED_EMAILS` set until rehearsal 2 is done: the 0009 build still requires an allowlist |
| Optional | `AOS_OIDC_PROVIDER_LABEL`, `AOS_WORKSPACE_CREATION`, `AOS_INVITATION_TTL_DAYS`, `AOS_RATE_ACCESS_REQUEST_PER_IP_HOUR`, `AOS_RETENTION_ACCESS_REQUEST_DAYS` | Defaults: derived label, `platform_admins`, 14, 5, 90 |
| **New (blueprint group)** | `AOS_TRUSTED_PROXY_HOPS=1` on the web service | Synced from the blueprint ([ADR 0025](../decisions/0025-client-address-behind-proxy.md)); check 12 confirms the value |
| New (hybrid and free blueprints) | `AOS_DB_POOL_SIZE=5`, `AOS_DB_MAX_OVERFLOW=5` | Synced from the blueprint; smaller pools for one shared instance (defaults 10 + 10 elsewhere) |
| New (all blueprints) | `AOS_STORE_FILES=false` | Synced from the blueprint; no file copies on Render's ephemeral disks ([ADR 0026](../decisions/0026-no-file-copies-on-render.md)) |
| Now optional | `AOS_PUBLIC_URL` | Defaults to Render's `RENDER_EXTERNAL_URL`; keep it only for a custom domain |

Migration 0010 copies every current workspace member onto the access list, so nobody who
already uses the deployment is locked out by the switch.

## 3. First sign-in and the first workspace

1. Open the service URL (`AOS_PUBLIC_URL`, or Render's `RENDER_EXTERNAL_URL` when unset), choose **Continue with Google**, and sign in with the platform admin
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

It checks liveness, readiness, `/version`, security headers (including HSTS, COOP and
Permissions-Policy), the SPA and CSP, that the API docs and metrics are not public, the auth
config, the redirect to the provider with PKCE and the right redirect URI, the login-binding
cookie's flags and `__Secure-` name, friendly callback errors, and that a cross-origin write is
refused. It is read-only.

| # | Check | How | Result |
| --- | --- | --- | --- |
| 1 | Build and deploy succeeded | Render Deploys page shows "Live" (web and worker, or the single service) | |
| 2 | Automated checks | `smoke_prod.py` exits 0 (attach `smoke.json`) | |
| 3 | Serving the expected commit | `smoke_prod.py --expect-commit <sha>`, or `GET /version`; the page footer shows `v<version> · <first 7 characters of the commit>` | |
| 4 | Sign-in | The platform admin signs in with Google; an uninvited account sees the request form | |
| 5 | Access request | Request access from a second account; approve it into the workspace as analyst; that account signs in and lands in the workspace | |
| 6 | Invitation | Invite a third address as reviewer; it joins with that role on first sign-in | |
| 7 | Workflow | Submit a brief with `(demo: unsupported claim)` in the topic → approve the plan → report v2 after a review round → the reviewer approves → the export downloads as *approved* | |
| 8 | Worker logs | Logs show `"worker started"`; no connection strings or secrets | |
| 9 | Restart safety | Restart the worker (or the single service) during research; the run resumes and the timeline shows no duplicate tasks | |
| 10 | Persistence | Redeploy; earlier runs, reports, documents and their search results are still there (Postgres). Exports download as before | |
| 11 | Access removal | Remove the analyst from the access list; their open session ends at the next request | |
| 12 | Client address ([ADR 0025](../decisions/0025-client-address-behind-proxy.md)) | (a) From your laptop, run the loop below: the 31st sign-in attempt within 5 minutes lands on `/signin?error=rate_limited` although every attempt forges a different `X-Forwarded-For`. (b) While the laptop is limited, a phone on mobile data can still open **Continue with Google**. If (a) fails, raise `AOS_TRUSTED_PROXY_HOPS`; if (b) fails, lower it | |

Check 12 (a), in PowerShell (`curl.exe` ships with Windows):

```powershell
1..31 | ForEach-Object { curl.exe -s -o NUL -w "%{redirect_url}`n" -H "X-Forwarded-For: 198.51.100.$_" https://<url>/api/v1/auth/login } | Select-Object -Last 1
```

The last line must end with `/signin?error=rate_limited`.

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
With the single-service blueprints, a failing start-up migration keeps the new instance from
becoming healthy, and Render keeps the old one.

### Rehearsal 1: code-only rollback

1. Note the live commit (`GET /version`). Deploy a newer commit that adds no migration.
2. Roll back to the noted deploy. Run
   `smoke_prod.py <url> --expect-commit <noted sha>`; sign in; open an existing run.
3. Roll forward again and repeat. Record times and results in [rehearsals.md](rehearsals.md).

### Rehearsal 2: rollback across the access-model migration (0010)

This proves the compatibility window. It needs the deployment to have run a build at
migration **0009** first. That is the first commit of this release, "Sign-in hardening,
schema compatibility window and deploy tooling" (`git log --oneline`). The 0009 build predates
the access model: it requires `AOS_ALLOWED_EMAILS` (set it to your own address) and ignores
`AOS_PLATFORM_ADMIN_EMAILS`. It also predates the `RENDER_EXTERNAL_URL` fallback, so set
`AOS_PUBLIC_URL` to the service URL on the web service. Keep all three set for the whole
rehearsal. With `render.yaml` only,
the 0009 build's worker also checks the web settings: copy `AOS_PUBLIC_URL`,
`AOS_OIDC_ISSUER`, `AOS_OIDC_CLIENT_ID` and `AOS_ALLOWED_EMAILS` onto `aos-worker` first.
Merge the release with a merge commit (not a squash), so the 0009 commit exists on `main`.

1. Deploy the 0009 build. `GET /version` shows `migration_head: "0009"`; `smoke_prod.py --older-build`
   passes; sign in and create a run.
2. Deploy the current build (0010). Migration 0010 runs; `/version` shows `"0010"`; record
   the smoke result, then submit and approve a plan.
3. **Roll back** to the 0009 deploy. Expected: the deploy goes live (readiness passes on the
   0010 schema); `smoke_prod.py --expect-commit <0009 sha> --older-build` passes (the 0009
   build predates the v1.0 security headers, which `--older-build` skips); existing runs open; the
   worker logs `"worker started"`, not "schema not compatible". The access-model pages are
   absent in this build, but sign-in works for allowlisted people.
4. Roll forward to the current build. Expected: no migration runs (already at 0010); the data
   created in steps 2-3 is intact; access requests and invitations work again.
5. Record each step with time, commit, `/version` output and smoke result in
   [rehearsals.md](rehearsals.md).

## Known limitations of this deployment

- `render.yaml` needs paid instance types for the worker and the pre-deploy command;
  `render.hybrid.yaml` trades that for a web service that sleeps when idle, and
  `render.free.yaml` adds a database that Render deletes after its free period.
- The blueprints keep no file copies (`AOS_STORE_FILES=false`,
  [ADR 0026](../decisions/0026-no-file-copies-on-render.md)): Render's disks are ephemeral and
  per service, and nothing reads a copy back. Uploads live on as extracted text in Postgres,
  and exports are rendered from Postgres on every download, so a redeploy loses nothing.
  Serving original files back would need an S3-compatible store first.
- `AOS_AGENT_MODE=fake`: deterministic demo agents, not a real model. To use a model, set
  `AOS_AGENT_MODE=llm` and the `AOS_LLM_*` variables on **both** services, within an approved
  budget (ADR 0005). Production refuses `AOS_SIGNUP_MODE=open` with model agents.
- A single web instance is assumed. Rate-limit and SSE state live in Postgres, so scaling out
  works, but it has not been load-tested on Render.
