# 0032: Rate limits never fail a run

- **Status:** Accepted
- **Date:** 2026-11-13
- **Amends:** [ADR 0029](0029-workspace-model-keys.md) (model chain), [ADR 0030](0030-labelled-model-fallback.md)
  (fallback scope), [ADR 0031](0031-open-sources-and-complete-passages.md) (open-search outages)
- **Requirements:** owner's report of a hosted Gemini run that failed in research with
  "worker: transient errors persisted after 5 attempts", after 13 model calls, 17 search calls
  and four collections of the same task's sources

## Context

- **Finished tasks were already checkpointed.** Each research task commits its result, and a
  retry skips committed tasks. Task t3 ran four times because *it* failed each time.
- **The failure was transient.** The Gemini client moved to another model on 404, 403 and 429,
  but raised a TransientError at once on 5xx (for example "the model is overloaded") and on
  timeouts. Every worker retry hit the same model again until five attempts were used.
- **A retry repeated the search.** The task searched and fetched again on every attempt, which
  explains the repeated "source collected" events and the extra search calls.
- **Search made no model calls.** The 17 "research search" entries in the cost table are search
  requests, metered separately.
- **The open search could fail a step.** It raised a TransientError when both Wikipedia and arXiv
  failed.

## Decision

1. **Rotate models on 429, 5xx and timeouts too.** The chain is the chosen model, then
   `gemini-4-hydrogen`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`, and last the paid-only
   `gemini-3.1-pro-preview`. Each model has its own free-tier quota. The request timeout is 90 s
   per model. Only when every model has failed this way does the client raise a TransientError.
   `gemini-3.5-flash` is not in the chain: Google routes it to 3.6 Flash.
2. **At most two requests in flight per key.** A process-wide semaphore per API key keeps parallel
   researchers from bursting through a requests-per-minute limit; extra calls wait their turn.
   Researchers use `thinkingLevel: low`.
3. **A retried task reuses its passages.** The researcher first reads the passages its task
   collected in an earlier attempt (`RunResearchTools.collected`). Only a task with none
   searches and fetches.
4. **A task always finishes.** If no model answers (TransientError after the chain, or
   StepFailed), the researcher's findings quote the first sentence of each collected passage and
   cite it, with no model call. Nothing is paraphrased or invented, so every finding is
   supported. The task records `fallback_reason`, and the timeline says the deterministic
   fallback did it.
5. **The planner, writer and reviewer** fall back to the deterministic agents on an exhausted
   TransientError as well as on StepFailed, labelled as before (ADR 0030).
6. **Open search never raises.** A source that is down, slow (6 s timeout) or rate-limited is
   skipped and logged; the task reports what it could not find. arXiv requests are spaced three
   seconds apart across parallel tasks, as its API terms ask.

**Declined:** "local deterministic technical reference synthesis" for search, that is, invented
passages when a site cannot be reached. A missing source is reported as missing.

## Consequences

- With `AOS_LLM_FALLBACK` on (the default), a run with a valid configuration reaches report
  approval even when every model is rate-limited. Each fallback step is labelled.
- The worker still retries real transient faults outside the model, such as Tavily outages and
  database interruptions, with its existing backoff.
- Tests: `tests/test_model_fallback.py` (rotation on 503 and timeout, two in flight, a run with
  every model rate-limited reaches report approval without worker retries, `collected()`
  against the database); `tests/test_data_pipeline.py` (evidence reuse and quoted findings,
  open-search outage).
