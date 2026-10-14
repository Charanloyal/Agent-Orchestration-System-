# Week-2 spikes deferred (NOT RUN)

PRD Week 2 also lists spikes for OIDC, search/fetch access and text-PDF extraction. Each
depends on a provider choice that is still **UNDECIDED**, so none has been run. Each plan below
is ready to execute once its decision is made.

## OIDC (blocked by identity-provider choice; Week 3)

- **Goal:** authorization code flow with PKCE against the chosen identity provider. Server-side
  session in an HTTP-only, Secure, SameSite cookie; CSRF token on mutations; logout.
- **Pass:** sign-in works locally; tokens never reach browser JavaScript or SSE query strings;
  a test client with a forged cookie is rejected.
- **Decide:** library choice, verified against its installed API, and session storage
  (PostgreSQL).

## Search and fetch (blocked by ADR 0003; Week 5)

- **Goal:** adapter call against the chosen provider with a small live budget (ADR 0005). Fetch
  returned URLs through the SSRF guard.
- **Pass:**
  - private, loopback, link-local and metadata addresses are rejected, including after
    redirects and DNS rebinding;
  - fetch failures are recorded as non-citable sources;
  - passages are stored with retrieval date and hash.

## Text-PDF extraction (needs no provider; scheduled with ingestion, Week 5)

- **Goal:** pick a library by testing synthetic text PDFs: plain, multi-column, encrypted,
  scanned (image only) and oversized.
- **Pass:** text and page locators extracted from text PDFs; encrypted and scanned files
  rejected explicitly; size, page and time limits enforced in an isolated process.
- **Why deferred:** it is independent of persistence. It is grouped with the ingestion
  milestone to keep Week 2 focused on the riskiest unknown (checkpoint fencing).
