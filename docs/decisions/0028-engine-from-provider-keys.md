# 0028: The engine follows the provider keys in the environment

- **Status:** Accepted; decisions 3 and 4 amended by [ADR 0029](0029-workspace-model-keys.md)
- **Date:** 2026-11-13
- **Requirements:** owner's request to leave demo mode by adding a Gemini, Groq or OpenAI key,
  without code changes; ADR 0005 (spending ceiling); ADR 0002 (OpenAI-compatible providers)

## Context

The hosted app ran the deterministic demo agents because `AOS_AGENT_MODE=fake` was pinned in
the blueprint. Switching to a model needed four variables (`AOS_AGENT_MODE`,
`AOS_LLM_API_KEY`, `AOS_LLM_BASE_URL`, `AOS_LLM_MODEL`) plus a blueprint change, sync and
deploy. The owner asked for two things:

1. paste a key into a settings page in the app, stored in the database, and switch modes at
   runtime;
2. or have the app detect `GEMINI_API_KEY`, `GROQ_API_KEY` or `OPENAI_API_KEY`.

## Decision

1. **Detection at start-up.** When `AOS_LLM_API_KEY` is unset, the first of `GROQ_API_KEY`,
   `GEMINI_API_KEY` and `OPENAI_API_KEY` that is set becomes the key, with that provider's
   OpenAI-compatible endpoint and a default model. Explicit `AOS_LLM_*` values always win.
   `TAVILY_API_KEY` works the same way for search.
2. **`auto` modes.** `AOS_AGENT_MODE=auto` means model agents when a key is configured and demo
   agents otherwise; `AOS_SEARCH_PROVIDER=auto` means Tavily when its key is set. The resolved
   mode is fixed for the life of the process. `render.free.yaml` uses `auto`, so adding a key in
   Render's Environment tab and saving (which restarts the service) is the whole switch.
   The paid blueprints keep `fake`, since their worker is a separate service.
3. **Keys stay in the environment.** They are not accepted through the API, stored in the
   database or shown anywhere. `/api/v1/auth/me` reports only the mode, the model name and the
   search provider, which the top bar shows as **Model agents · <model>** or **Demo agents**.
4. **No runtime switch.** The engine changes only with a restart.

## Alternatives considered

- **Keys in the database through a settings page.** Rejected:
  - a database dump, a backup or an SQL mistake would expose a billable credential;
  - every admin session would become a path to the key, so it would need encryption at rest
    with a key that itself lives in the environment, which brings back the original problem;
  - Render already stores environment values encrypted and restricts who can see them.
- **A runtime mode switch.** Rejected: runs in flight were planned under one engine and would
  finish under another, which would make their provenance records (provider, model and
  prompt version per artifact) misleading. A restart is a clean boundary.

## Consequences

- Going live is "add `GROQ_API_KEY`, save" (deploy-render.md section 6). Removing the key and
  deploying returns to demo agents.
- The budget ledger still reserves the estimated cost before each call. Price settings default
  to small-model list prices, so a free tier is overestimated, never underestimated.
- Provider differences remain: a provider that rejects JSON mode or `seed` needs
  `AOS_LLM_RESPONSE_FORMAT=none` or `AOS_LLM_SEED=`. Only Groq-style and OpenAI behaviour are
  covered by existing adapter tests, so the live smoke test is required before relying on a
  provider.
- Tests: `tests/test_engine_config.py`; the top-bar pill in `AppShell.test.tsx`.
