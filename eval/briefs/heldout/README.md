# Held-out evaluation briefs: authoring procedure

This folder is intentionally empty of cases. The 20 held-out briefs must be written **after
the development set is frozen** and **without looking at system outputs**. Otherwise they leak
into tuning (see [evaluation plan](../../../docs/evaluation/evaluation-plan.md)).

## Procedure

1. Freeze `eval/briefs/dev/` by tagging the commit (for example `eval-dev-v1`).
2. Ideally, someone who has not tuned prompts writes the cases. If that's impossible, write them
   before any multi-agent prompt tuning and record that limitation.
3. Use the same category mix as dev: 8 answerable, 3 conflicting evidence, 3 unavailable
   evidence, 2 stale sources, 2 malicious content, 2 provider failure. Keep the domain the same,
   and do not reuse dev topics.
4. Name files `heldout-01.json` … `heldout-20.json` with `"split": "heldout"`. Validate them with
   the `EvalCase` contract.
5. Commit them in a single reviewed change. After that, do not edit a case except to fix a
   schema error, and log any such fix in the evaluation results.
6. Do not use held-out cases in prompt development, demos or CI smoke tests.
