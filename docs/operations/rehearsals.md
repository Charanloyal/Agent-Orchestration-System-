# Deployment and rollback records

Evidence for the manual items in [p0-checklist.md](p0-checklist.md). Fill in one block per
attempt; attach the `smoke_prod.py --json` output next to this file
(`docs/operations/records/`). An empty block means *not done yet*.

Status as of 2026-11-12: **deployed** (`render.free.yaml`, owner's Render and Google accounts).
Rollback rehearsals and the hosted checks 4-11 are still open. Steps:
[deploy-render.md](deploy-render.md).

## Deployment verification

| Field | Value |
| --- | --- |
| Date, time (UTC) | 2026-11-12 09:31 |
| Blueprint | `render.free.yaml` (free web service, free Postgres, `singapore`); chosen because the paid database needs a card |
| Service URL | https://aos-web-8b4t.onrender.com |
| Commit (`GET /version`) | `ce682e54bfb7` |
| Migration head (`GET /version`) | `0010` |
| `smoke_prod.py` result | **27/27 passed** with `--expect-signup-mode request --expect-commit ce682e5`, file [records/2026-11-12-smoke-ce682e5.json](records/2026-11-12-smoke-ce682e5.json) (run by the agent from the owner's laptop) |
| Check 12 (client address) | **Failed with `AOS_TRUSTED_PROXY_HOPS=1`**: 32 sign-in attempts within a minute were never rate-limited, with a forged rotating `X-Forwarded-For` and also without one. Fixed in `582db43` (two hops, [ADR 0025](../decisions/0025-client-address-behind-proxy.md)); to be repeated once that commit is live |
| Checks 4-11 of the verification table | Not yet recorded (need the owner's sign-in) |
| Done by | Owner (Render, Google); agent (smoke test, check 12) |

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
