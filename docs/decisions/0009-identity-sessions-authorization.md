# 0009: Identity, sessions and workspace authorization

- **Status:** Accepted
- **Date:** 2026-10-14
- **Requirements:** FR-01, non-negotiable #1, threat-model T3 and T11

## Decisions

1. **OIDC authorization code flow with PKCE (S256).** The backend acts as a
   provider-agnostic client (`app/auth/oidc.py`).
   - It discovers endpoints from `/.well-known/openid-configuration` and checks that the
     issuer matches the configured one.
   - It verifies ID tokens against the JWKS: signature (RS256/PS256/ES256 only; never `none`
     or HMAC), `iss`, `aud`, `exp`, `iat` and `sub`, plus a nonce comparison.
   - An email is trusted only when `email_verified` is not false.
2. **Login state** (state, nonce, PKCE verifier, `next`) is stored server-side in
   `oidc_login_states`, keyed by the SHA-256 of `state`. Each entry is single-use and expires
   after 10 minutes. `next` must be a same-origin relative path, which blocks open redirects.
3. **Server-side sessions.**
   - The cookie holds an opaque random token: `HttpOnly`, `SameSite=Lax`, and `Secure`
     (required in prod). The database stores only its SHA-256.
   - Sessions slide on activity and expire after 8 hours.
   - Logout deletes the session row.
   - Tokens from the identity provider are not kept.
4. **CSRF:** every unsafe request (POST/PUT/PATCH/DELETE) must send `X-CSRF-Token` equal to the
   session's CSRF token, and any `Origin` header must equal `AOS_PUBLIC_URL`. This is
   enforced inside `get_principal`, so a route cannot forget it.
5. **Authorization:**
   - A role (`analyst`, `reviewer`, `admin`) is assigned per workspace membership.
   - A single permission table (`app/policy/permissions.py`) maps roles to actions.
   - **Non-members get 404**, so resource IDs never leak.
   - The last admin of a workspace cannot be removed or demoted.
6. **Dev identity provider:** `devtools/dev_oidc.py` is a minimal, standards-shaped issuer
   (PKCE required, RS256, JWKS, single-use codes) used for demos and tests. It refuses
   `AOS_ENV=prod` and binds to 127.0.0.1 by default. Real providers (Google, Microsoft Entra
   ID) need only configuration: issuer, client ID and client secret.
7. **Back-channel URL:** `AOS_OIDC_BACKCHANNEL_URL` lets server-to-server calls reach the
   issuer at an internal address (Docker Compose), while the `iss` claim is still checked
   against the public issuer.

## Verification

- The real dev issuer is served over HTTP in tests: full sign-in, single-use state, unknown
  state, logout.
- ID-token negatives: wrong nonce, audience or issuer; expired; missing `sub`; unknown key;
  `alg=none`; HS256.
- `tests/test_authz.py` builds the route list from the OpenAPI schema. Every
  `/api/v1` route is checked for 401 when unauthenticated; every unsafe route for 403 without
  CSRF, with a wrong token, or from a cross-origin request; every resource route for **404 to
  a member of another workspace**. New routes are covered automatically.

## Consequences

- Workspace-scoped routes use `workspace_access(Action)`. Run-scoped routes (Week 4+) load the
  run's workspace first and then apply the same check.
- Members are added by email only after the user has signed in once (no invitation system
  in v1).
