# 0002: Model provider

- **Status:** Proposed. Decision **UNDECIDED**.
- **Date:** 2026-10-14

## Context

The pilot needs one hosted LLM provider behind an adapter (PRD §3.1). Until a provider is
chosen, all development and CI use a deterministic fake model; the spike already does this.
The choice affects:
- cost,
- data retention and training terms,
- structured-output support,
- rate limits,
- regional availability.

## Decision criteria

1. **Data terms:** no training on API inputs; a documented retention period; region. Mandatory
   for any non-public data.
2. **Structured output:** JSON-schema-constrained output or reliable tool calling. This reduces
   repair attempts but does not replace server-side Pydantic validation.
3. **Cost transparency:** published per-token prices; usage returned per response so it can be
   reconciled.
4. **Limits:** documented rate limits, `Retry-After` behaviour and idempotency support.
5. **Access:** what the developer can legally and practically use, including any employer
   policy on external AI services.

## Options

| Option | Notes to verify before deciding |
| --- | --- |
| A. Major hosted model API used directly | Check current data-use terms, structured-output support and price sheet |
| B. The same model family through a cloud platform (an enterprise cloud AI service) | May fit the deployment target (ADR 0004) and corporate data agreements; check regional availability |
| C. Self-hosted open-weights model | No per-token fees, but adds GPU and operations work outside pilot scope; only if data terms rule out A and B |

## Consequences (any option)

- The adapter interface is `complete(structured request) -> (raw output, usage)`. Validation and
  the bounded repair stay in our code (spike S5).
- Record the provider, model ID, parameters and prompt version on every step.
- Live calls need a budget under [ADR 0005](0005-spending-ceiling.md).

**Decision owner:** project lead. **Revisit by:** before Week 6 (planner on a live model).
