# Held-out evaluation briefs

**Status:** written (20 cases, `heldout-01` … `heldout-20`). **No system has been run on them.**

## How they were written

1. The development set was frozen first: git tag `eval-dev-v1` (commit `37556c4`, where
   `eval/briefs/dev/` last changed).
2. The cases were then written by the same author (the coding assistant) who built the system,
   **before any prompt tuning** and without running any system on them. This is weaker than
   independent authorship, and it is recorded as a threat to validity in the evaluation report.
3. They use the same category mix as dev (8 answerable, 3 conflicting evidence, 3 unavailable
   evidence, 2 stale sources, 2 malicious content, 2 provider failure), the same domain
   (software engineering tooling) and new topics. `test_heldout_topics_do_not_reuse_dev_topics`
   checks that the topics differ.
4. They are validated by the `EvalCase` contract (`test_split_has_twenty_valid_cases_with_the_planned_mix`).
   Their corpus folders are under `eval/corpus/v1/heldout-*`.

## Rules (leakage)

- Do not use held-out cases in prompt development, demos or CI smoke runs. CI only validates
  their schema.
- The harness refuses `--split heldout` without `--confirm-heldout`.
- Run them only for the evaluation milestone's live run and the release review. Any system
  change made after seeing held-out results invalidates that run for claims.
- After the first run, do not edit a case except to fix a schema error, and log any such fix
  in the results.
