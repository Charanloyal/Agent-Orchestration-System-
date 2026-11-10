# Blind scorer brief (one page)

For the two classmates who score the live evaluation. They did not build the system and are
never named in this repository: record them as `S1` and `S2` only.

## What you are doing (for the scorers)

You will read short research reports written by three AI systems about software products and
judge whether each factual claim is backed by the source passage it cites. You will not know
which system wrote which report. About 2–3 hours each, at your own pace, alone.

1. You receive a folder with `claims.csv`, `coverage.csv`, `must_not.csv`, `reports/` and
   `INSTRUCTIONS.md`. Read `INSTRUCTIONS.md` first; it defines every column.
2. Fill in the CSV files in a spreadsheet. Put your scorer id (`S1` or `S2`) in every row.
3. Judge only against the cited passage, not what you know about the product.
4. Do not discuss reports with the other scorer until both of you have handed in.
5. If anything is unclear, ask the coordinator, who answers both scorers in the same words.
6. Hand back the three CSV files. Nothing you write is graded; there are no right answers to
   aim for, and disagreement between scorers is expected and measured.

Data: public product documentation and synthetic briefs only; no personal data.

## Procedure (for the coordinator, the project owner)

1. After the live dev or held-out run:
   `python -m evaluation.blind ..\eval\results\<run folder>` (from `backend/`).
2. Copy `<run folder>\scoring\` **without `KEY.json`** to each scorer separately. Keep
   `KEY.json` on your machine only until both have handed in.
3. Collect the files as `scoring\S1\` and `scoring\S2\`, then merge:
   `python -m evaluation.score <run folder>\scoring <run folder>\scoring\S1 <run folder>\scoring\S2`.
   It writes `human_scores.json` with raw agreement, Cohen's kappa and every disagreement.
4. Resolve disagreements by discussion, record how in the run folder's notes, and report
   both the pre-discussion kappa and the resolved scores.
5. Report results with denominators and Wilson 95% intervals (eval/results/README.md, final
   report §13.5, §14, §17). Fake-agent runs are never scored for quality.
