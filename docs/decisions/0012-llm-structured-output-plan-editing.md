# 0012: LLM adapter, structured output, prompt versioning, plan editing and approval expiry

- **Status:** Accepted
- **Date:** 2026-10-15
- **Requirements:** FR-03, FR-04, non-negotiables #4 and #13; PRD §3.1 (log provider, model,
  parameters and prompt version)

## Decisions

1. **One adapter for every provider:** `OpenAICompatibleLlm` (`app/providers/llm.py`), built
   on the official `openai` SDK with `max_retries=0`.
   - Configuration: base URL, model and key; `AOS_LLM_API_STYLE=azure` switches to Azure
     OpenAI.
   - Works with OpenAI, Azure OpenAI, Groq and Ollama.
   - Error classification:
     - timeouts, connection errors, 429 and 5xx → `TransientError` (honouring
       `Retry-After`), retried only by the worker, with bounded backoff;
     - 400/401/403/404/422 → `StepFailed`, never retried.
2. **JSON mode, not strict schema mode.** Requests use `response_format={"type":
   "json_object"}`, which providers support widely, plus the JSON Schema in the prompt.
   Strict schema mode is not portable: it rejects optional fields and defaults.
   Correctness is enforced by our own validation.
3. **Bounded repair** (`app/agents/structured.py`):
   - Output is parsed (tolerating code fences), then validated against the Pydantic
     contract.
   - Server-side checks such as `enforce_plan_policy` run as part of the same validation.
   - On failure, **exactly one** repair turn lists field locations and messages. It never
     includes the previous output or any source text.
   - A second failure becomes a visible `StepFailed`.
4. **Prompts are versioned code** (`app/agents/prompts.py`, for example `planner/v1`).
   Changing a prompt means bumping its version.
   - Every stored plan or report version carries `generation` metadata (provider, model,
     prompt version, attempts, input and output tokens), added by migration 0004.
   - Timeline events carry the same summary, never the prompt or output text.
5. **The server owns versions and policy.** The model's `plan_version` is overwritten, and
   the tool allowlist and task limit come from the brief (`plan_policy_for`), not from model
   output.
6. **Plan editing** (`PUT /api/v1/runs/{id}/plan`, analyst or admin, only while awaiting
   plan approval):
   - It creates a new immutable version (`author: user`), with optimistic concurrency on
     `base_version`.
   - The edit is re-validated against the contract and policy.
   - Older versions' digests no longer match, so approvals of them are rejected with 409.
   - The workflow resumes with the approved, edited plan.
7. **Run-scoped authorization happens before body parsing** (`run_access` dependency).
   Untrusted input is never processed for callers who may not act on the run. The
   route-generated authz matrix caught the original ordering.
8. **Approval-wait expiry:** worker maintenance (`expire_overdue_waits`) moves overdue waits
   to `EXPIRED`, using `SKIP LOCKED` so it can never race a decision in progress. Late
   decisions get 409.
9. **Live tests are opt-in** (`-m live`, `AOS_LIVE_TESTS=1`) and are excluded by default and
   in CI (ADR 0005).

## Agent rollout

`AOS_AGENT_MODE=llm` uses the LLM planner now. The researcher (M7), writer and reviewer (M8)
switch to LLM implementations behind the same `AgentSuite` interfaces.
