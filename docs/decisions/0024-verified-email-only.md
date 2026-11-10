# 0024: Trust only provider-verified email addresses

- **Status:** Accepted
- **Date:** 2026-11-10
- **Requirements:** ADR 0009 (identity), ADR 0021 (access model); finding G2 (P0)

## Context

Every sign-in decision uses the email in the ID token: platform admins, the allowlist, the
access list, invitations and access requests. `verify_id_token` used
`claims.get("email_verified", True)`, so a token *without* the claim counted as verified.
Google always sends `email_verified`, but other providers may omit it, and Microsoft Entra ID
never sends it: an Entra account can carry an `email` claim the tenant never checked. With the
old default, such an address could match someone else's invitation or admin entry.

## Decision

1. An email is trusted only when the token says so explicitly: `email_verified` must be the
   JSON boolean `true`. Missing, `false`, a string such as `"true"`, or any other value means
   unverified. An `email` without `@` is ignored.
2. **Microsoft Entra ID** (issuer host `login.microsoftonline.com`): the email is trusted when
   the optional claim `xms_edov` ("email domain owner verified") is `true`. Operators add it in
   the app registration (Token configuration > Add optional claim > ID > `xms_edov`). A
   single-tenant issuer (`https://login.microsoftonline.com/<tenant-id>/v2.0`) is recommended
   on top, so only that tenant's accounts can sign in at all. `xms_edov` from any other issuer
   is ignored.
3. An unverified sign-in still authenticates the person at the provider, but the app sees no
   email: they get the existing "did not confirm an email address" page, no user row and an
   audited denial. The display name never falls back to an unverified address.

## Alternatives considered

- **Trust the email for a single-tenant Entra issuer without `xms_edov`.** Simpler setup, but
  tenant guests and synced accounts can carry addresses from domains the tenant does not own.
  Rejected; `xms_edov` answers the actual question.
- **Accept string `"true"`.** Some non-compliant providers send strings. The OpenID Connect
  spec defines a boolean, and accepting looser values only widens what counts as verified.

## Consequences

- Google sign-in is unchanged. The dev issuer sends `email_verified: true`.
- A provider that omits the claim now yields "did not confirm an email address" until it is
  configured to send it (or, for Entra, `xms_edov`).
- Tests: `test_only_an_explicitly_verified_email_is_trusted` (true, false, missing, string,
  number) and `test_microsoft_entra_vouches_with_xms_edov_only`.
