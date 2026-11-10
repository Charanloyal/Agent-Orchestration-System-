# 0021: Access model: invitations, access requests and platform admins

- **Status:** Accepted
- **Date:** 2026-11-06
- **Requirements:** PRD FR-01 (authorization), pilot onboarding; threat model T1, T2, T18-T20;
  ADR 0009 (identity, sessions, authorization); findings B2 (callback errors), B3 (no
  invitations)

## Context

Until now, who could sign in was decided by two environment variables (an email and a domain
allowlist), and a person could only be added to a workspace after they had signed in once.
A public deployment needs more: a way for strangers to ask for access without learning who is
already in, a way for workspace admins to invite people who have no account yet, and a person
who can administer access for the whole deployment from the app. Sign-in failures returned
raw JSON error pages, and the callback accepted a valid `state` from any browser.

## Decision

1. **Who may sign in.** A *verified* email (the provider's `email_verified` is `true`; a
   missing claim counts as unverified, ADR 0024) may sign in when
   any of these holds, in this order:
   1. it is a **platform admin** (`AOS_PLATFORM_ADMIN_EMAILS`, required in production);
   2. it is on the **environment allowlist** (`AOS_ALLOWED_EMAILS`, `AOS_ALLOWED_EMAIL_DOMAINS`);
   3. it is on the in-app **access list**;
   4. it has a pending, unexpired **workspace invitation**;
   5. the **signup mode** is `open`.
2. **Signup modes** (`AOS_SIGNUP_MODE`):
   - `invite` (production default): only the sources above;
   - `request`: the same, plus a public form on the sign-in page. Platform admins approve
     (optionally straight into a workspace with a role) or deny;
   - `open`: anyone with a verified email (development default without an allowlist).
     Production refuses `open` together with model agents, because strangers could spend
     model budget.
3. **Access requests never reveal anything.** `POST /api/v1/access-requests` answers `202`
   with the same body whether the email is new, already pending, already allowed, or was
   denied. Only one pending request per email is stored. It requires a same-origin request,
   is limited per client address (`AOS_RATE_ACCESS_REQUEST_PER_IP_HOUR`, default 5), and
   writes an audit event without the email. Decided requests are deleted after
   `AOS_RETENTION_ACCESS_REQUEST_DAYS` (default 90).
4. **Invitations.** Workspace admins invite by email and role
   (`POST /api/v1/workspaces/{id}/invitations`). Someone who already has an account is added
   at once (`status: added`). Otherwise the invitation (default 14 days,
   `AOS_INVITATION_TTL_DAYS`) is accepted automatically at that email's first sign-in. An
   invitation never changes the role of an existing member. Accepting one also puts the
   email on the access list, so later sign-ins work. No email is sent: the admin tells the
   person to sign in.
5. **The access list** (platform admins, `/api/v1/admin/access-list`). Removing an entry
   revokes the email's pending invitations and deletes all its sessions, so the person is
   signed out everywhere. Memberships and work are kept, so access can be restored. Migration
   0010 copies every current workspace member onto the list, so switching an existing
   deployment to `invite` locks nobody out.
6. **Admin routes answer 404** to everyone who is not a platform admin, like
   workspace-scoped routes do for non-members (ADR 0009).
7. **Workspace creation** (`AOS_WORKSPACE_CREATION`): `everyone` in development,
   `platform_admins` by default in production.
8. **Sign-in hardening.**
   - `/login` sets a short-lived login cookie (`aos_login`; `__Secure-aos_login` in prod)
     (HttpOnly, SameSite=Lax, Secure in
     production, path `/api/v1/auth/callback`, 10 minutes) holding the `state`. The callback
     requires it. A valid `state` replayed in another browser (login CSRF) is refused.
   - Every failure redirects to `/signin?error=<code>` with one of `provider_denied`,
     `provider_error`, `provider_unavailable`, `login_expired`, `login_failed`,
     `email_unverified`, `not_allowed` or `rate_limited`. The UI explains each one.
     Operators get the actionable detail in the logs.
   - `GET /api/v1/auth/config` (public) returns the provider label for "Continue with ..."
     and the signup mode. It reveals no account data.
   - Google's two documented `iss` forms are both accepted when the issuer is Google.

## Consequences

- Platform admins are configured in the environment rather than in the database, so a
  database compromise cannot add one, and a mistake in the UI cannot remove the last one.
  Changing them needs a redeploy.
- Sign-in decisions happen before a user row exists. People who are refused leave no
  account, only an audit event without their email.
- Requests are throttled per client address. A distributed attacker can still fill the
  pending list. It is bounded by one pending row per email, and denying in bulk is a
  documented operator task.
- Without email delivery, invitations depend on the admin telling the person. The settings
  page says so and shows the address to sign in at.
