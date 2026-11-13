# 0030: A permanent model error falls back to the deterministic agent, visibly

- **Status:** Accepted
- **Date:** 2026-11-13
- **Requirements:** owner's report of a live run failing at planning with "model provider
  rejected the request (HTTP 400)", and the requirement that a demonstration never ends in a
  failed run

## Context

With Gemini configured, a run failed at the planner with HTTP 400 and no further detail:
both adapters discarded the provider's error body. Google answers several different problems
with 400, including an invalid key ("API key not valid") and settings a model or account
does not accept. The adapter never sent `responseSchema`; the JSON schema is in the prompt
and the reply is parsed and validated by our code (`agents/structured.py`), so a schema
format was not the cause.

## Decision

1. **Say why.** Both adapters put the provider's own message in the error, for example
   `HTTP 400: INVALID_ARGUMENT: API key not valid`, with the key replaced by `***` and the
   text cut at 300 characters. The settings **Test connection**, the timeline and the
   run's failure reason show it.
2. **One plain retry.** If Gemini rejects a request with 400 for any reason other than the
   key, the adapter retries once with only `maxOutputTokens`: no JSON mode, no thinking
   budget. The agents parse JSON from plain text as well. Key and model ID are normalised
   (whitespace, a `models/` prefix, case).
3. **Native Gemini for environment keys too.** A `GEMINI_API_KEY` set on the server now uses
   the native adapter, like a key saved in workspace settings, instead of Gemini's
   OpenAI-compatible endpoint.
4. **Labelled fallback** (`AOS_LLM_FALLBACK`, default on). If a model step fails permanently
   (`StepFailed`: rejected request, or output still invalid after the repair round), that
   step is done by the deterministic agent. Its artifact records `fallback_reason` and
   `fallback_from`. The timeline says "…, by the deterministic fallback (model failed: …)",
   with the provider's reason for diagnosis. The plan or report card says only "Written by
   the built-in agent: the language model was unavailable for this step." That note stays:
   hiding it would misstate who wrote the artifact, and the reason belongs in the timeline,
   not in a publication-ready card. Transient errors (timeouts, 429, 5xx) are still retried by the
   worker first and are not masked. The evaluation harness never uses the fallback, so
   measured results are always the model's.
5. **Search** *(superseded by [ADR 0031](0031-open-sources-and-complete-passages.md): without a
   key, research now uses open sources, Wikipedia and arXiv).* The model's own background
   knowledge is **not** turned into "evidence": every cited passage must come from a fetched
   source or an uploaded document, which is the system's central guarantee.

## Consequences

- A live demonstration reaches the approval gates even with a wrong key. The page is honest
  about which steps the model did not write, and the timeline gives the reason to fix.
- A run can mix model-written and fallback steps, and each artifact says which.
- Tests: `tests/test_model_fallback.py` (a run completes against a provider that rejects
  everything; without fallback it fails with the provider's reason; the plain retry; no
  retry and no key leak for a bad key; normalisation), `src/format.test.ts`.
