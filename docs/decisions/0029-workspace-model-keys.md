# 0029: Workspace admins can save a model key in the app (encrypted)

- **Status:** Accepted
- **Date:** 2026-11-13
- **Amends:** [ADR 0028](0028-engine-from-provider-keys.md), decisions 3 and 4
- **Requirements:** owner's decision that an in-app engine panel is required: "paste a Gemini
  key in Settings, test it, and the app runs live"

## Context

ADR 0028 kept model keys only in the server environment. The owner overruled that for this
project: a workspace admin must be able to choose Google Gemini, Groq or OpenAI in workspace
settings, paste a key, test it and switch the workspace to live agents without a redeploy.
The risks ADR 0028 named are still real, so this decision limits them instead of ignoring them.

## Decision

1. **Per workspace.** `workspace_ai_configs` (migration 0011) holds one row per workspace:
   provider (`gemini`, `groq`, `openai`), model (from a fixed list per provider), the key as
   a Fernet token, and the key's last 4 characters. Deleting the workspace deletes it.
2. **Encrypted at rest.** The Fernet key is derived from `AOS_SECRETS_KEY`, which the Render
   blueprints generate. In production, saving a key without it is refused (409). If the
   secret changes, saved keys fail to decrypt and the workspace falls back to the
   deployment's engine with a visible warning; nothing crashes.
3. **Never returned.** No API returns the key. `GET .../ai-config` returns the engine source
   (`workspace`, `environment` or `demo`), provider, model and the 4-character hint. Saving
   and removing are audited without the key.
4. **Who.** Every member can see which engine runs. Only workspace admins can save, test or
   remove a key (`workspace.manage`); the test endpoint is rate-limited
   (`AOS_RATE_AI_TEST_PER_USER_HOUR`, default 30).
5. **Precedence.** The workspace's key, then the deployment's environment (ADR 0028), then the
   demo agents. The worker resolves the engine at the start of each pass. Every stored
   artifact records the provider and model that produced it, so a change takes effect at the
   next step and provenance stays truthful.
6. **Gemini natively.** Gemini uses its own REST API (`models/{model}:generateContent`), with
   the key in the `x-goog-api-key` header, never in the URL, JSON output through
   `responseMimeType`, and thinking switched off for Flash models so the agents keep their
   output budget. Groq and OpenAI use the OpenAI-compatible client.
7. **Style studio.** With a live engine, the model rewrites the document. The rewrite is
   accepted only if the fact lock is complete and the Markdown structure is unchanged; it gets
   one correction round, then the built-in rules are used. The page shows which engine wrote
   the result. Style rewrites are rate-limited but not metered against a run budget, so the
   admin's provider-side spending limit is the cap. The settings card says so.

## Consequences

- Going live: **Settings → AI engine → Google Gemini → paste key → Test connection → Save**.
  The top bar shows **⚡ Live · gemini-3.8-flash** at once, and new runs use the model.
- A database leak alone does not expose keys. A leak of both the database and
  `AOS_SECRETS_KEY` does, so treat the secret like the database password.
- Tests: `tests/test_ai_engine.py` (encryption, never-returned key, permissions, model list,
  live test without saving, Gemini request shape and error classes, style fallback);
  `WorkspaceSettingsPage.test.tsx`; `AppShell.test.tsx`.

## Amendment (2026-11-13): current Gemini models

Google deprecated `gemini-2.5-flash` and `gemini-2.5-pro`: they are no longer selectable in
AI Studio and are routed to newer models from 1 December 2026. `gemini-3.5-flash` already
routes to `gemini-3.6-flash`. Sources: Gemini API *Models*, *Deprecations* and *What's new in
Gemini 3.8 Flash* pages, read 2026-11-13.

1. **Models offered, in fallback order:** `gemini-3.8-flash` (default), `gemini-3.5-flash-lite`,
   `gemini-3.6-flash`. When the chosen model answers 404 (unknown or retired for this key), or
   429 (its quota is used up), the adapter tries the next one. It never moves on for a bad
   key or a bad request. The model that answered is recorded in usage and provenance.
2. **Retired IDs are mapped at runtime:** 2.0/2.5/3.0/3.7 Flash and 2.5 Pro become
   `gemini-3.8-flash`, and 3.5 Flash becomes `gemini-3.6-flash`. This applies to saved
   workspace settings, `AOS_LLM_MODEL` and the API, so nobody has to re-save. `GEMINI_API_KEY`
   now defaults to `gemini-3.8-flash`.
3. **Gemini 3 request settings:** no `temperature` (Gemini 3 ignores it, and later generations
   will reject it with 400); `thinkingConfig.thinkingLevel = "low"` for 3.8 and 3.6 Flash
   (never `minimal`, which 3.8 Flash rejects); Flash-Lite keeps its default. Thinking tokens
   count against `maxOutputTokens`, so 4,096 tokens of headroom are added. They are billed as
   output, so the budget ledger counts them (`thoughtsTokenCount`).
