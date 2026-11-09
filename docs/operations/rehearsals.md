# Deployment and rollback records

Evidence for the manual items in [p0-checklist.md](p0-checklist.md). Fill in one block per
attempt; attach the `smoke_prod.py --json` output next to this file
(`docs/operations/records/`). An empty block means *not done yet*.

Status as of 2026-11-06: **blocked by owner**. No Render deployment exists yet; it needs
the owner's Render and Google Cloud accounts (and payment details for `render.yaml`). Steps:
[deploy-render.md](deploy-render.md).

## Deployment verification

| Field | Value |
| --- | --- |
| Date, time (UTC) | |
| Blueprint | `render.yaml` / `render.free.yaml` |
| Service URL | |
| Commit (`GET /version`) | |
| Migration head (`GET /version`) | |
| `smoke_prod.py` result | e.g. 21/21 (22 with `--expect-commit`), file `records/<date>-smoke.json` |
| Checks 4-11 of the verification table | pass/fail each, with notes |
| Done by | |

## Rehearsal 1: code-only rollback

| Step | Time (UTC) | Commit | `/version` | Smoke | Notes |
| --- | --- | --- | --- | --- | --- |
| Live before | | | | | |
| Deployed newer commit | | | | | |
| Rolled back | | | | | |
| Rolled forward | | | | | |

Outcome and time to recover:

## Rehearsal 2: rollback across migration 0010

| Step | Time (UTC) | Commit | `/version` (`migration_head`) | `/readyz` | Smoke | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1. 0009 build live | | | `0009` | | | run created: |
| 2. 0010 build live | | | `0010` | | | plan approved: |
| 3. Rolled back to 0009 build | | | `0009` (schema stays 0010) | expect 200 | | worker log: |
| 4. Rolled forward | | | `0010` | | | data intact: |

Outcome:
