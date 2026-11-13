# 0033: Relevant sources only, and every uploaded passage reaches the writer

- **Status:** Accepted
- **Date:** 2026-11-13
- **Amends:** [ADR 0031](0031-open-sources-and-complete-passages.md) (open search, whole short documents)
- **Requirements:** owner's report on run 0e5612a0: off-topic Wikipedia pages (Sick building
  syndrome, Pattern (sewing), International Space Station, a gravitational-wave catalogue, and
  an adult-content article) entered the evidence and were listed in the Executive Summary; the
  writer marked the CV's NeuralGateway project as unknown

## Context

- **Open search matched generic words.** Wikipedia full-text search received the question's
  first six non-stop words, including "pattern", "building" and "transient". Any article with
  those words came back, and no check compared a result with the question.
- **The reviewer asked for it.** With off-topic passages in the evidence, the reviewer asked the
  writer to say so, and the writer listed their subjects.
- **The CV was collected whole but not shown whole.** `search_uploads` returned all four
  passages. The writer, however, reads at most 24 passages, chosen round-robin across tasks
  from evidence ordered by evidence id, which is a hash. The order was therefore random, and
  passages 3 and 4 (the projects) were not among those chosen.

## Decision

1. **Relevance filter on open-search results.** A result is kept only if its title or first
   1,500 characters contain at least two of the question's keywords, at least one of them
   distinctive. Generic words such as "pattern", "building", "system", "design", "data",
   "transient" and "performance" are not distinctive. Wikipedia and arXiv are queried with the
   distinctive words only.
2. **No adult content.** A result whose title or opening mentions pornography, sexual content,
   nudity and similar terms is dropped, unless the question itself is about that subject.
3. **Official documentation first.** A short directory maps well-known engineering topics to
   their official pages: circuit breakers (Martin Fowler), Raft, FastAPI streaming responses,
   MDN server-sent events, Qdrant indexing, the Faiss wiki, Spark Structured Streaming, Redis Lua
   scripting, LangGraph, Kubernetes, PostgreSQL MVCC and Docker. Every URL was checked before it
   was added.
   - A matching question gets up to two of these pages before the open-search results.
   - Only the address is stored. The page is fetched live through the safe fetcher, so its text
     is the vendor's own, and the workspace domain policy applies.
   - Triggers match whole words only, so "raft" does not match "draft" and "sse" does not match
     "assess".
4. **Uploaded documents first.**
   - Evidence is loaded per task with uploaded passages first, in document order ("passage 10"
     after "passage 2"), then web sources in collection order.
   - The writer and reviewer receive every uploaded passage (up to 25), then web passages
     round-robin across tasks, up to 36 in total.
   - Documents of up to 25 passages are read whole (was 15).
   - When full-text search matches no uploaded passage, the workspace's short documents are
     returned whole anyway.
5. **Prompts (writer/v2, reviewer/v2).**
   - The writer ignores off-topic passages: it never cites, summarises or lists them. A question
     the relevant evidence does not answer gets an `unknown` claim instead.
   - The reviewer never asks the writer to describe irrelevant sources.

**Declined:**
- **Built-in passages written into the search provider.** Text written by us or by a model and
  cited to a vendor's URL would be a fabricated citation. The directory stores addresses only.
- **A whitelist allowing only computer-science results.** It would break briefs on any other
  subject. The relevance filter compares each result with the question instead.

## Consequences

- Fewer but relevant open-search results. A question with no relevant source gets an honest
  `unknown` claim.
- Old runs keep their evidence. A new run is needed to see the change.
- If a curated page moves, its fetch fails and is recorded like any other failed fetch.
- Tests in `tests/test_data_pipeline.py`:
  - the run's off-topic and adult pages are rejected while the relevant article is kept;
  - generic-word-only matches are rejected;
  - curated hits use whole terms and respect the domain policy;
  - the writer receives every uploaded passage first;
  - evidence loads uploads first, in natural document order.
