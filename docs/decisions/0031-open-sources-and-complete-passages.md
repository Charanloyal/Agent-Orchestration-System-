# 0031: Real open sources, complete passages, short documents whole

- **Status:** Accepted
- **Date:** 2026-11-13
- **Amends:** [ADR 0030](0030-labelled-model-fallback.md), decision 5 (search)
- **Requirements:** owner's review of a live Gemini 4 run: the report's *Limitations* said the
  web passages came from the fake search provider, and that resume passages broke off
  mid-word ("CI fault-injection t", "Trained 5 M")

## Context

Three faults, each reported correctly by the model:

1. **The hosted app searched nothing real.** Without a search key, the blueprints used the
   deterministic test provider, whose pages say they are synthetic.
2. **Passages were cut mid-word.** The writer and reviewer cut every passage to 900
   characters (`PASSAGE_CHARS`) before showing it to the model, and the chunker could split
   inside a sentence. That is where "fault-injection t" came from.
3. **Short documents arrived in pieces.** Upload search returned the five best-matching
   passages, and the researcher kept three, so the sections between headings of a two-page
   resume never reached the writer.

## Decision

1. **Keyless open search** (`AOS_SEARCH_PROVIDER=open`; `auto` without a Tavily key now means
   `open`). It uses Wikipedia (plain-text article extracts through the MediaWiki API) and arXiv
   (abstracts through the arXiv API). Both publish free APIs for programmatic use. The text is
   the source's own, cited by its real URL and revision or publication date, and the domain
   policy applies. If both are unreachable, the step is retried as a transient error.
   **Not done**, and why:
   - **scraping DuckDuckGo or Google result pages:** their terms forbid automated access;
   - **Gemini "knowledge synthesis" as evidence:** text written by the model and attached to
     documentation URLs would be a fabricated citation. Every passage must come from the
     document it cites (FR-05);
   - **Gemini grounding with Google Search:** a legitimate search source, but not available on
     the free tier (Gemini API pricing, read 2026-11-13). A paid key can use Tavily.
2. **Complete passages.** The chunker normalises PDF text: line endings, soft hyphens, words
   hyphenated across lines, and runs of spaces. It packs whole lines and sentences into
   passages of about 1,600 characters (at most 2,000). Only a single sentence longer than
   2,000 characters is ever cut, at a word boundary. The writer and reviewer receive whole
   passages; a safety cap keeps whole sentences only. There is no overlap between passages:
   they end on boundaries, and overlap would put the same text into two citable passages.
3. **Short documents whole.** When a matching document has at most 15 passages, upload search
   returns all of them in order. The researcher reads uploads first (up to 15 passages), then
   web results, within 24 passages per task.
4. **Re-indexing.** `POST /workspaces/{id}/uploads/reindex` (**Re-index documents** on the
   Documents page, for analysts and admins) rebuilds passages from the stored ones, so it
   works without the original file (ADR 0026). Old passages of one page are re-joined first:
   with a space where the old chunker cut inside a sentence, with a line break where it had
   ended one. Evidence already cited by runs keeps its own copy and does not change. The
   action is audited.
5. **Style studio from an approved report.** **✨ Open in Style studio** next to the approved
   download hands the report to the Style studio as Markdown: sections as headings, claims as
   paragraphs, and citations as `[n]` so the fact lock keeps them. The rewrite is a separate
   copy. The approved report, its digest and its export do not change, and no export record
   is created.

## Consequences

- Hosted runs, demo and live, cite real public sources. Without a Tavily key the coverage is
  encyclopaedic and academic, not vendor documentation or news. The *Limitations* section
  will say so when that matters, which is accurate.
- The CI and test suites keep the deterministic provider (`AOS_SEARCH_PROVIDER=fake`); the open
  provider is tested against recorded API shapes (`tests/test_data_pipeline.py`).
- Tests: `tests/test_data_pipeline.py`, `RunPage.test.tsx`, `UploadsPage.test.tsx`.
