# P0 pilot go-live checklist

Tick each item only with the evidence named. "Automated" items are re-verified by CI on
every push; "manual" items must be redone for each environment.

## A. Workflow (automated)

- [x] Brief → plan → plan approval → bounded parallel research → cited draft → review →
      bounded revision → approval of the exact version → export (`test_workflow.py`,
      `test_review_export.py`, E2E `workflow.spec.ts`).
- [x] A rejected plan produces a new version; a rejected report cannot be exported as
      approved (`test_plan_rejection_creates_new_version`,
      `test_rejected_report_exports_only_as_draft`).
- [x] Stale or wrong-version approvals are refused; a changed report needs a new approval
      (`test_stale_and_wrong_kind_decisions_rejected`).
- [x] Cancel, retry, crash recovery (`test_cancel_retry.py`, `test_worker_recovery.py`).

## B. Security (automated)

- [x] Production refuses the dev issuer, insecure cookies, http URLs, a missing platform
      admin, and open signup with model agents
      (`test_unsafe_production_settings_refuse_to_start`).
- [x] Only admitted, verified emails sign in: platform admins, allowlist, access list,
      invitations; requests reveal nothing; admin routes are invisible to others
      (`test_access.py`, E2E `access.spec.ts`).
- [x] Sign-in is bound to the browser that started it; every failure ends on a friendly page
      (`test_auth_oidc.py`).
- [x] Workspace isolation on every route; CSRF/Origin on unsafe methods (`test_authz.py`).
- [x] SSRF blocked; injected URLs never fetched (`test_fetcher.py`; evaluation fixtures).
- [x] Oversized bodies rejected; rate limits with `Retry-After` (`test_pilot_and_lifecycle.py`,
      `test_observability.py`).
- [x] No secrets or content in logs, traces, metrics or the audit log (`test_logging.py`,
      `test_observability.py`, CI `deploy-image` log scan).
- [x] OpenAPI and interactive docs disabled in prod; dev issuer absent from the production
      image (`test_production_app_hides_openapi_and_docs`, CI `deploy-image`).

## C. Operations

- [x] `/readyz` is 503 unless the schema is at the code's head or a newer schema that lists
      the code as compatible; never on an older schema (automated; ADR 0020).
- [x] Rolling back across an additive migration keeps the previous build ready
      (`test_previous_build_stays_ready_on_a_newer_compatible_schema`).
- [x] The production image migrates, starts web and worker, passes `smoke_prod.py`, and stops
      the worker gracefully; the single-service variant does the same (CI `deploy-image`).
- [x] Worker survives a database outage and waits for migrations (automated).
- [x] Backup/restore drill on isolated databases: PASS, 28 tables and 1,250 rows identical
      ([load-and-recovery.md](load-and-recovery.md)).
- [x] Load: 20 concurrent readers p95 158 ms with 0 errors; 2 × 5 concurrent workflows with
      0 integrity violations; crash takeover within the lease (same document; local machine,
      fake providers).
- [x] Alert rules and incident runbook ([alerts.yml](alerts.yml), [runbook.md](runbook.md)).
- [ ] **Manual, per environment (in progress, 2026-11-12):** deployed at
      https://aos-web-8b4t.onrender.com (`render.free.yaml`); Google OAuth client registered;
      `AOS_PLATFORM_ADMIN_EMAILS` set; `smoke_prod.py` 27/27. Open: check 12 after `582db43`
      (two proxy hops) and checks 4-11 with the owner's sign-in, recorded in
      [rehearsals.md](rehearsals.md).
- [ ] **Manual (blocked by owner):** rollback rehearsal 1 (code only) and rehearsal 2 (across
      migration 0010) on the hosted environment, recorded in [rehearsals.md](rehearsals.md).

## D. Data and honesty

- [x] Retention and deletion policy published ([data-retention.md](data-retention.md)); the
      public-demo data policy is shown to pilot users.
- [x] Fake-agent mode is labelled in the UI, the docs and the evaluation results.
- [x] Render keeps no file copies on its ephemeral disks (`AOS_STORE_FILES=false`, ADR 0026);
      uploads and exports work from Postgres alone (`test_uploads.py`, `test_review_export.py`,
      CI `deploy-image`).
- [ ] **Open (blocked by owner):** live-model evaluation and blind human scoring (needs an
      API key, a budget approval within USD 10 and two scorers).

## E. Usability and accessibility

- [x] axe-core WCAG 2.2 A/AA scan of every page, light and dark mode; 360 px layouts;
      keyboard test (E2E `a11y.spec.ts`).
- [ ] **Open (blocked by owner):** NVDA screen-reader session, zoom and forced-colours checks
      ([accessibility-checklist.md](../product/accessibility-checklist.md)).
- [ ] **Open (blocked by owner):** interviews and the five-person usability study
      ([interview-guide.md](../product/interview-guide.md),
      [usability-study.md](../product/usability-study.md)).
