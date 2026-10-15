# 0011: Evidence ingestion: search, safe fetching, extraction, uploads and retrieval

- **Status:** Accepted
- **Date:** 2026-10-15
- **Requirements:** FR-05, FR-01; threat model T2 (SSRF), T8 (malicious files), T1 (injection)

## Decisions

1. **Search adapters** share one interface, which returns hits and billing units (credits)
   for the cost ledger:
   - **Tavily** (`app/providers/tavily.py`): Bearer key; domain include and exclude lists;
     published dates. 429 and 5xx responses map to `TransientError` (honouring
     `Retry-After`); 4xx, plan-limit (432) and pay-as-you-go (433) errors map to
     `StepFailed`, with no retry.
   - **Offline corpus** (`app/providers/corpus.py`): BM25 over versioned JSON documents, for
     reproducible evaluation at no cost.
   - **Fake:** deterministic, for tests.
2. **We fetch pages ourselves** (`include_raw_content=false`), so retrieval time, content
   hash, and redirect handling are ours.
3. **SSRF-safe fetcher** (`app/tools/fetcher.py`):
   - Only http/https on ports 80/443, with no credentials in URLs.
   - Our own DNS resolution: **every** resolved address must be public (Python `is_global`,
     plus IPv4-mapped, 6to4 and Teredo unwrapping). Otherwise the request is rejected before
     any connection is opened.
   - The connection is **pinned** to a vetted IP through a custom httpcore network backend,
     which defeats DNS rebinding; TLS still verifies the original hostname.
   - Redirects are followed manually; every hop is re-validated, and the final URL must still
     satisfy the brief's domain policy.
   - Limits: 2 MB, 10 s, and an allowlist of content types (HTML, plain text, PDF).
   - Environment proxies and cookies are ignored.
   - **Private-API dependency:** the transport replaces `HTTPTransport._pool`. This is pinned
     with httpx 0.28.1; `tests/test_fetcher.py` must pass on any upgrade.
4. **Extraction** (`app/tools/extract.py`):
   - HTML is parsed with the stdlib parser; script, style, iframe, nav, footer and form
     content is dropped.
   - Text-PDF parsing (pypdf) runs in a **separate process with a timeout**
     (`app/tools/pdf_worker.py`). Encrypted, scanned (no text layer), corrupt and over-long
     PDFs are rejected with explicit reasons.
   - Injected instructions inside documents are kept verbatim as *data*. They are never
     executed or obeyed.
5. **Failed fetches are first-class records:** a `sources` row with `fetch_status='failed'`
   and a reason. They are never evidence, never citable, and appear in the UI as
   "Not read".
6. **Uploads:**
   - The file type is **sniffed from content** (PDF magic bytes, or UTF-8 text with a
     .txt/.md name), never taken from the client's Content-Type.
   - The size limit is 10 MB; filenames are sanitized.
   - Files are de-duplicated per workspace by SHA-256 and stored behind an `ObjectStore`
     interface (local filesystem now, S3-compatible later). Keys are server-generated, and
     every read goes through a workspace-authorized route.
7. **Retrieval:** PostgreSQL full-text search (generated `tsvector` columns with GIN
   indexes) over upload chunks and run evidence. pgvector is deferred until a measured
   baseline justifies it (PRD §3.1).
   - The workspace filter is applied in SQL *before* ranking (FR-01).
   - User searches use web-search semantics (all words).
   - Research questions use any-word matching ranked by coverage, because requiring every
     word in "How often do keys rotate?" misses relevant passages. An E2E test caught this.
8. **Tool policy follows the brief**, not the model: web tools only if web or vendor sources
   are allowed; `search_uploads` only if uploaded documents are allowed
   (`app/policy/tools.py`).

## Consequences

- Live search and fetch need outbound internet. Behind an authenticating corporate proxy,
  the proxy must enforce equivalent egress rules; the fetcher will not tunnel through it
  silently.
- Upload deletion removes the stored file and its searchable chunks. Passages already copied
  into a run's evidence remain part of that run's immutable record (retention: M13).
