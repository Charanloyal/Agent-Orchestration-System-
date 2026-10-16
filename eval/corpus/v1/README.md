# Offline evaluation corpus v1

A small, versioned document collection for reproducible, cost-free evaluation runs
([ADR 0017](../../../docs/decisions/0017-evaluation-harness.md)). Search uses BM25 over one folder
per case (`<case_id>/docs/`), so cases never see each other's documents.

## What the documents are

All 80 documents were written for this project. There are two kinds, recorded per document in
[MANIFEST.json](MANIFEST.json):

- **Paraphrase** (title ends with "(paraphrase)"): a short summary, in our own words, of public
  documentation on a real topic. The URL points at the original so readers can verify it. The
  text is **not** a quotation, and it may simplify or lag behind the original.
- **Fictional**: an invented product on a reserved `.example` domain, used to create conflicting,
  stale, missing, malicious or failing evidence on purpose.

The `attribution` field of every document repeats this. Do not cite the corpus as evidence
about the real products.

## Fixtures

`<case_id>/fixture.json` turns a case's prose `fixture_notes` into something the harness can
execute:

| Key | Meaning | Cases |
| --- | --- | --- |
| `search_faults` | The first `times` searches fail with the given HTTP status, then succeed | dev-19, heldout-19 |
| `model_fault` | Every model call fails (`http_500` or `timeout`) | dev-20, heldout-20 |
| `uploads` | Text files uploaded to the run's workspace before the brief is submitted | dev-18, heldout-18 |

Cases with no `docs/` folder or no documents (heldout-13) deliberately return no search
results.

## Deliberate source-policy probe

`dev-02/docs/dedicated-engine-ops.json` sits on a domain that dev-02's brief does not allow
(`allowed_domains: [postgresql.org]`). The workflow must filter it out, so the question it
would answer is expected to come back as unknown. `test_corpus_documents_respect_their_case_source_policy`
fails if any other document is outside its case's policy.

## Changing the corpus

The corpus is part of the experimental setup. Any change requires all of these:

- regenerating `MANIFEST.json`, so its hashes match;
- bumping the version (`v2`) if results have already been reported;
- recording the change in the evaluation results.

Held-out folders must not be edited after a held-out run.
