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

- [x] Production refuses the dev issuer, insecure cookies, http URLs and a missing sign-in
      allowlist (`test_unsafe_production_settings_refuse_to_start`).
- [x] Uninvited accounts cannot sign in (`test_allowlist_refuses_uninvited_accounts…`).
- [x] Workspace isolation on every route; CSRF/Origin on unsafe methods (`test_authz.py`).
- [x] SSRF blocked; injected URLs never fetched (`test_fetcher.py`; evaluation fixtures).
- [x] Oversized bodies rejected; rate limits with `Retry-After` (`test_pilot_and_lifecycle.py`,
      `test_observability.py`).
- [x] No secrets or content in logs, traces, metrics or the audit log (`test_logging.py`,
      `test_observability.py`, CI `deploy-image` log scan).
- [x] OpenAPI and interactive docs disabled in prod; dev issuer absent from the production
      image (`test_production_app_hides_openapi_and_docs`, CI `deploy-image`).

## C. Operations

- [x] `/readyz` is 503 until the schema is at the code's migration head (automated).
- [x] The production image migrates, starts web and worker, serves the SPA and stops the
      worker gracefully (CI `deploy-image`).
- [x] Worker survives a database outage and waits for migrations (automated).
- [ ] Backup/restore drill on isolated databases ([load-and-recovery.md](load-and-recovery.md), M14).
- [x] Alert rules and incident runbook ([alerts.yml](alerts.yml), [runbook.md](runbook.md)).
- [ ] **Manual, per environment:** identity provider registered; allowlist set; the 10-step
      verification in [deploy-render.md](deploy-render.md#4-verify-the-deployment) recorded.
- [ ] **Manual:** rollback rehearsed once on the hosted environment (redeploy the previous
      build).

## D. Data and honesty

- [x] Retention and deletion policy published ([data-retention.md](data-retention.md)); the
      public-demo data policy is shown to pilot users.
- [x] Fake-agent mode is labelled in the UI, the docs and the evaluation results.
- [ ] **Open:** live-model evaluation and blind human scoring (needs an API key, a budget
      approval and two scorers).
