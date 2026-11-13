# 0027: Writing Style Studio with measured metrics and a fact lock

- **Status:** Accepted
- **Date:** 2026-11-13
- **Requirements:** owner's request for a "humanizer" with persona rewrites; project rule
  "honest claims only"

## Context

The owner asked for a feature that rewrites text in a chosen voice (journalist, academic,
executive, technical) and makes reports read less like boilerplate. The request also asked
for an "AI-detector bypass" with a "95%+ success rate".

Two problems with that second part:

1. **It cannot be claimed honestly.** Detectors disagree with each other, change without
   notice and have documented false-positive rates on human writing. Any success rate would
   depend on which detector, which version and which text, so no measurement here could
   support a fixed number.
2. **It is evasion, not quality.** A tool built and advertised to hide machine authorship
   from detectors is mainly useful for academic or editorial dishonesty. That is out of scope
   for a project whose central promise is that people approve exactly what leaves the system.

The part that is useful and measurable is improving prose: varying sentence rhythm, removing
stock phrases, and adapting the register to a reader, without changing any fact.

## Decision

1. A **Style Studio** page and two endpoints,
   `POST /api/v1/workspaces/{id}/style/analyze` and `/style/rewrite`. Each takes exactly one of
   pasted `text` (at most 50,000 characters) or an `upload_id` from the workspace. Members with
   read access may use them; others get 404. Calls are rate-limited per user
   (`AOS_RATE_STYLE_PER_USER_HOUR`, default 120).
2. **Metrics describe the text, nothing else:**
   - sentence-length variation (coefficient of variation);
   - vocabulary diversity (moving-average type-token ratio, window 50) and word entropy;
   - stock phrases per 1,000 words, with the sentences that contain them highlighted;
   - paragraph-length variation.

   The page states that these are "not a prediction of who or what wrote it". No score is
   presented as a detector result or as a probability of authorship.
3. **Fact lock.** Numbers, dates, percentages, quoted text, bracketed citations and URLs are
   extracted before the rewrite and compared exactly afterwards. A sentence change that would
   alter any of them is rejected and counted, and the page shows "facts preserved n / n".
4. **Deterministic rewrite** (`backend/app/services/style.py`), up to three passes:
   - replaces stock phrases, except those a persona keeps (academic keeps formal transitions);
   - undoes "not only … but also";
   - splits long sentences at ", and/but/so" or ";", never inside quotes or brackets; how
     long counts as long differs by persona.

   The same input always gives the same output, costs nothing and needs no model key.
5. **No detector-evasion features or claims** anywhere in the code, UI or documentation.

## Alternatives considered

- **Model-based rewrite.** Rewrites more fluently, but costs money per call, needs the budget
  ledger and still needs the same fact lock, because models change numbers and quotes. It
  can be added later behind `AOS_AGENT_MODE=llm`, with the fact lock as its guard.
- **Detector bypass with a published success rate.** Rejected for the reasons in *Context*.
- **A single "human-likeness" score.** Rejected: it would read as a detector verdict. Separate
  named measurements are explainable and cannot be mistaken for authorship evidence.

## Consequences

- The feature works on the free deployment without keys and is fully testable:
  `tests/test_style.py`, `tests/test_style_api.py`, the authorization matrix in
  `tests/test_authz.py`, `src/pages/StylePage.test.tsx` and `e2e/style.spec.ts`.
- The rewrite is conservative: it improves rhythm and removes boilerplate, but it does not
  restructure arguments or invent content.
- If someone asks in the viva whether it "beats detectors", the answer is that it was not
  designed to, and why.

## Amendment (2026-11-13): structure, openers, measured rhythm, voices

The first version flattened Markdown: lists and headings separated by single line breaks ran
together, and the page printed sentences without their paragraphs. It also left templated
openers such as "In today's rapidly evolving technological landscape," in place, and its
rhythm splits could make sentence lengths *more* uniform. Changes:

1. **Markdown-aware.** The text is parsed into blocks: headings, paragraphs, list items, block
   quotes, code, tables and blank lines. Only headings (phrases only), paragraphs and list
   items are rewritten. Markers, blank lines and order are kept exactly; quotes, code and
   tables are copied verbatim. A line that ends a sentence followed by a capitalised line is
   kept as its own paragraph, so text pasted with single line breaks keeps its shape.
2. **Templated openers** are removed or restructured:
   - "In today's … landscape," and "In an era of …," are removed;
   - "As X delve into Y, Z" becomes two sentences;
   - "Not only does X …, but it also …" becomes two sentences, but only when the subject can
     be found safely;
   - "Key pillars driving X include:" becomes "X rests on:";
   - noun-phrase list items become actions ("The deployment of" → "Deploying").
3. **Rhythm is guided by the measurement.** A split of a long sentence, or a join of two short
   ones where the second starts with a pronoun, is kept only if it raises the document's
   sentence-length variation. The rewrite therefore never flattens the rhythm it reports.
4. **Voices differ in vocabulary.** Academic expands contractions; executive drops hedges
   ("basically", "very", "arguably"); journalist prefers plain verbs ("purchase" → "buy");
   technical drops vague intensifiers. Quoted words are never edited.
5. **The page** shows the measurements as rings (the outer arc is after, the inner arc before),
   a sentence-rhythm chart, a formatted preview with highlights, a list of changes with their
   rules, and the Markdown source. It exports .md, .txt and .docx (built in the browser, no new
   dependency) and copies clean text. A clearly labelled synthetic sample loads with one click.

Requested again and **declined again**: a "Humanizer accuracy ≥ 95%" score and pass
probabilities for Turnitin, GPTZero or Originality.ai. No detector was run, so such numbers
would be invented. A tool advertised to get past them would serve academic dishonesty. The
page keeps "These are measurements of the text, not a prediction of who or what wrote it."
