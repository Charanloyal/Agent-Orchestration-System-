# Week-2 spikes deferred (NOT RUN)

> **Historical (Week 2).** The provider decisions were made afterwards (ADR 0002, 0003, 0009
> and, for deployment, 0018 and 0023), and these areas were then built and tested directly in
> their milestones instead of as separate spikes.

PRD Week 2 also lists spikes for OIDC, search/fetch access and text-PDF extraction. Each
depended on a provider choice that was still undecided in Week 2, so none was run. Each plan below
was ready to execute once its decision was made.

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
