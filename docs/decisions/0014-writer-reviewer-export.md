# 0014: Writer, reviewer loop, persisted findings and report export

- **Status:** Accepted
- **Date:** 2026-10-15
- **Requirements:** FR-06 (writer), FR-07 (reviewer), FR-11 (export); threat model T6, T7

## Context

The writer and reviewer were deterministic fakes, and review findings existed only in
checkpoint state. The PRD needs three things:

- Reports built **only** from collected evidence, with a bounded review loop of at most 2
  rounds.
- An auditable record of what the reviewer flagged.
- An export that cannot pass a draft off as approved.

## Decisions

1. **Two-layer review.** `deterministic_findings` (`app/agents/review_checks.py`) runs on
   every draft, in fake and LLM mode alike:
   - **Numeric fidelity:** every number in a *fact* must appear in a cited passage or its
     source title. Otherwise it is a **blocker**.
   - **Lexical support:** a *fact* sharing under 20% of its content words with its cited
     passages is a **major** finding.

   The LLM reviewer (`reviewer/v1`) adds semantic findings. `merge_reviews` can only make the
   outcome **stricter**: a model `pass` becomes `revise` if any blocker or major finding
   exists. Model finding IDs are re-keyed `m{n}-…` so they cannot collide with `d-…` IDs.
2. **The LLM writer (`writer/v1`) sees evidence only.**
   - Passages are capped at 24, chosen round-robin across tasks, truncated, and delimited
     with the same neutralised `<passage>` wrapper the researcher uses.
   - Server-side checks inside the single repair: every cited ID must be among the provided
     passages, and every section ID must be in the approved outline.
   - Review findings from the previous round are passed back explicitly.
   - The graph still re-validates citations against all run evidence before persisting.
3. **Findings are persisted** in `review_findings`, keyed by (run, report version, finding
   ID).
   - They are written in the same fenced transaction as the `review_completed` event, with
     ON CONFLICT DO NOTHING, so a re-executed reviewer node is idempotent.
   - Each finding records its `source` (`deterministic` or `model`).
   - `GET /runs/{id}/reviews` returns rounds with their findings. The UI highlights the
     flagged claims and can jump to the superseded version that contained them.
4. **Export is `POST /reports/{id}/versions/{v}/export`, not GET.**
   - It records a `report_exports` row, an audit entry and a timeline event, and stores the
     bytes in the object store. A side-effecting route belongs behind the CSRF and Origin
     checks.
   - The response is an `attachment` with `nosniff`, `X-Export-Kind` and
     `X-Content-SHA256`.
5. **Approved or draft is decided server-side.**
   - An export is `approved` only if an approval exists for this exact version **and
     digest** with decision `approve`. It then embeds the approver, time and digest.
   - Anything else, including rejected reports, is watermarked
     `DRAFT - NOT APPROVED` at the top and bottom.
6. **Markdown is escaped, not sanitised after the fact.**
   - All model and source text is flattened to one line, every Markdown-structural
     character is backslash-escaped, and `&` is encoded.
   - Only `http(s)` URLs become links, percent-encoded so they cannot break out of the link.
   - Exports contain no images or remote resources.
7. **Demo hook.** In fake mode, a brief whose topic contains `(demo: unsupported claim)` gets
   one fabricated figure in report v1. This demonstrates catch → revise → pass without a
   model. It is a test and demo aid only, documented in the fake writer.

## Consequences

- The deterministic checks are cheap, explainable and cannot be talked out of a finding.
  They are also shallow: they miss paraphrased misstatements and can flag legitimate
  paraphrases. Semantic support remains the job of the model reviewer and the human
  reviewer. The evaluation (M11) measures this rather than assuming it.
- Reviewer and writer calls are metered like every other LLM call (steps `writer` and
  `reviewer` in `/usage`).
- Export bytes are reproducible from stored artifacts except for the export timestamp. The
  SHA-256 of each export is recorded.
