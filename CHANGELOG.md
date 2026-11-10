# Changelog

All notable changes to this project. Dates are UTC. Versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - unreleased (tag `v1.0.0` after the owner's approval)

The first release meant to be used by people other than its author: anyone can be invited
or ask for access, and the deployment can be verified and rolled back safely. Nothing has
been deployed yet; the hosted steps are prepared and listed under *Not done*.

### Added

- **Access model** ([ADR 0021](docs/decisions/0021-access-model.md)):
  - platform admins (`AOS_PLATFORM_ADMIN_EMAILS`, required in production);
  - signup modes `invite`, `request` and `open` (`AOS_SIGNUP_MODE`);
  - in-app access list; removing someone signs them out everywhere;
  - public access requests that answer identically for every email, rate-limited per client;
  - workspace invitations by email and role, accepted at first sign-in;
  - workspace creation limited to platform admins by default in production;
  - migration 0010; current members are carried onto the access list.
- **Sign-in:** "Continue with Google/Microsoft/..." from the issuer
  (`AOS_OIDC_PROVIDER_LABEL` to override); each sign-in bound to its browser by a short-lived
  cookie; every failure explained on the sign-in page; both Google issuer forms accepted;
  public `GET /api/v1/auth/config`.
- **UI:**
  - welcome page for people without a workspace;
  - workspace settings: rename, roles, removal, invitations;
  - access administration with a pending-requests badge;
  - request-access form on the sign-in page;
  - notifications for every action, session-expiry redirect that returns you to the same
    page, and plain-language 403 messages;
  - dark mode, layouts down to 360 px, keyboard-operable confirmations, favicon and meta
    tags.
- **Operations:**
  - schema compatibility window, so the previous build stays ready after an additive
    migration and rollbacks need no schema change
    ([ADR 0020](docs/decisions/0020-schema-compatibility-window.md), migration 0009);
  - `GET /version` (build, commit, migration head);
  - `backend/scripts/smoke_prod.py`, a read-only production smoke test, run in CI against the
    production image;
  - `render.free.yaml` and `python -m app.serve --migrate --with-worker` for a single free
    service ([ADR 0022](docs/decisions/0022-deployment-variants-ephemeral-storage.md));
  - deployment guide for Google OAuth and Render, with two rollback rehearsals and a records
    page.
- **Tests:** access model, login binding, compatibility window, smoke script, single-service
  runner; Vitest suites for every new page; Playwright journeys for invitations, access
  requests and session expiry; an axe-core WCAG 2.2 A/AA scan of every page in light and dark
  mode, a 360 px layout check and a keyboard test.
- **Research preparation:** recruiting message, consent note, usability task script and
  record, WCAG 2.2 AA checklist.

### Changed

- Render blueprints: retention off (runs and uploads kept until deleted, for the viva); no file
  copies on Render's ephemeral disks (`AOS_STORE_FILES=false`, [ADR 0026](docs/decisions/0026-no-file-copies-on-render.md));
  database pool sizes are settings (`AOS_DB_POOL_SIZE`, `AOS_DB_MAX_OVERFLOW`), budgeted against
  Render's 100 connections; the public URL defaults to Render's `RENDER_EXTERNAL_URL`.
- One Docker health check fits each role (`python -m app.healthcheck`: web, worker, or both).
- `/healthz` and the page footer show the version and the deployed commit.
- Corpus search refuses to start without corpus documents instead of finding nothing.
- ADR 0004 (local demo only) is superseded by ADR 0018 and 0023 (Render).
- Production no longer requires an email allowlist. It requires at least one platform admin;
  the allowlist remains an optional "always allowed" list.
- OIDC callback errors redirect to `/signin?error=...` instead of returning JSON.
- `/readyz` and worker start-up accept a newer schema that declares the build compatible,
  and say clearly when a schema is behind or no longer compatible.
- Re-uploading a file whose stored original was lost restores it (where copies are kept;
  the Render blueprints keep none, ADR 0026).
- Data tables hide secondary columns on narrow screens.
- Frontend dev dependency `undici` updated to 8.12.4 (security advisories in 8.0.0-8.12.1).

### Security

- Rate-limit keys use the client address appended by the trusted proxy, counted from the
  right of `X-Forwarded-For` (`AOS_TRUSTED_PROXY_HOPS`; [ADR 0025](docs/decisions/0025-client-address-behind-proxy.md));
  a forged header no longer resets the sign-in or access-request limits.
- Only an explicit `email_verified: true` (Entra: `xms_edov`) counts as a verified email
  ([ADR 0024](docs/decisions/0024-verified-email-only.md)).
- Production adds HSTS, `Cross-Origin-Opener-Policy` and `Permissions-Policy`; cookies are
  `__Host-aos_session` and `__Secure-aos_login` (people signed in before signs in once more).
- ID tokens must carry exactly the issuer named by discovery (fixes Auth0 issuers ending in `/`).

- Threat model revised: T18 (enumeration and spam through access requests), T19 (login
  CSRF), T20 (privilege escalation through invitations), T21 (rollback to an incompatible
  build), T22 (loss of originals on an ephemeral disk).

### Not done (blocked by owner)

- Render deployment, its verification and both rollback rehearsals (Render and Google Cloud
  accounts).
- Live-model evaluation and blind human scoring (API key, budget approval, scorers).
- Interviews, the usability study and the screen-reader session (participants).

## [0.4.0] - 2026-11-05

Milestones M3-M16: workflow, evidence, budgets, reviewer loop, recovery, observability,
evaluation harness, production image, data lifecycle, reliability, UX and the final report.
See [docs/README.md](docs/README.md).
