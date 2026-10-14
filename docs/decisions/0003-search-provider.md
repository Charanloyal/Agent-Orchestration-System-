# 0003: Search provider

- **Status:** Proposed. Decision **UNDECIDED**.
- **Date:** 2026-10-14

## Context

The pilot needs one licensed search API behind an adapter (PRD §3.1). Search is not
unrestricted crawling. Page fetching is a separate, SSRF-guarded step that runs only for URLs
returned by search or allowed by the brief's source policy. Until a provider is chosen, a fake
search adapter returns deterministic synthetic passages.

## Decision criteria

1. **Terms of use:** programmatic use allowed; storing excerpts allowed; attribution required.
2. **Controls:** domain allow and block filters, date filters, and result metadata (URL, title,
   date).
3. **Cost and limits:** published per-query price and rate limits; behaviour under 429.
4. **Quality on the dev briefs:** measured on the 20 development cases using the same fetch
   pipeline.

## Options

| Option | Notes to verify |
| --- | --- |
| A. General web search API from a major search engine | Check current API availability, terms for storing results, and pricing |
| B. Search API built for LLM/RAG use | Often returns extracted content; check whether storing content is allowed and how sources are attributed |
| C. Vendor-documentation-only search (site-restricted) | Narrower but more predictable; may fit the pilot domain |

## Consequences

- The adapter returns `(url, title, snippet, published_on?)`. Snippets are never used as
  evidence on their own; evidence is fetched and stored passages (FR-05).
- Run a quality comparison on the dev set before committing, if two options are viable.

**Decision owner:** project lead. **Revisit by:** before Week 5 (search adapter).
