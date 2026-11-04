# Demonstration script (about 10 minutes)

A complete, reproducible walkthrough of the workflow with the **deterministic fake agents**.
No model provider or money is needed. Every step names the automated test that proves the
same behaviour, so the demo is not the only evidence.

## Before the audience arrives

PowerShell, from the repository root; PostgreSQL running as in the [README](../../README.md#1-database).

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.cli seed-demo --sample-run     # prints the sample run URL
```

Start the four processes, each in its own terminal:

```powershell
cd backend; .\.venv\Scripts\python.exe -m devtools.dev_oidc                   # identity provider :8001
cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000    # API
cd backend; .\.venv\Scripts\python.exe -m app.workers.runner                  # worker
cd frontend; npm.cmd run dev                                                   # web app :5173
```

Optionally start a second worker to show that two workers share the queue safely.

Check that <http://127.0.0.1:5173> shows **API available** on the sign-in page.

The example brief is [`backend/app/demo_brief.json`](../../backend/app/demo_brief.json). Its
topic contains `(demo: unsupported claim)`, which makes the fake writer plant one
fabricated figure in report v1, so the reviewer has something real to catch.

## The walkthrough

| # | Say | Do | Evidence (automated) |
| --- | --- | --- | --- |
| 1 | "An analyst submits a research brief." | Sign in as **Alice Analyst**. Open the sample run printed by `seed-demo`, or click **New brief**, paste the example topic and questions, and submit. | `test_happy_path_brief_to_approved_report`; E2E `analyst submits a brief…` |
| 2 | "The planner turns it into a structured, typed plan." | Open the **Plan** tab: tasks grouped by dependency level, tools per task, the report outline. | `test_contract_plan.py`; planner policy tests |
| 3 | "Nothing runs until a person approves this exact plan version." | Point at the digest under the decision panel. Optionally **Edit plan** (creates v2), then **Approve plan**. | `test_stale_and_wrong_kind_decisions_rejected`; `test_plan_rejection_creates_new_version` |
| 4 | "Research tasks collect evidence with provenance." | Watch the live timeline: sources collected per task. Open **Evidence**: passages with source, retrieval date, publication date and hash. | `test_research_sources.py`; `test_fetcher.py` (SSRF) |
| 5 | "Tasks run in parallel within the brief's limits and budget." | Point at the timeline (two tasks at a time) and the **Cost** card (estimated, reserved before each call). | `test_fan_out_is_parallel_but_bounded…`; `test_concurrent_reservations_never_exceed_the_budget` |
| 6 | "The writer drafts a report from evidence only." | **Report** tab: every claim is labelled Fact, Inference, Conflict, Recommendation or Unknown, with numbered citations. Click a citation to see the exact passage. | `test_llm_writer_prompt_is_evidence_only…` |
| 7 | "The reviewer checks claims against their cited passages." | Scroll to **Review**: round 1 found a *blocker*, an invented figure. Click the claim id; it jumps to v1 and highlights the claim. | `test_planted_unsupported_claim_is_caught_revised_and_persisted` |
| 8 | "The writer revised it, within at most two review rounds." | Switch back to **v2**: the claim is gone and the limitation is disclosed. Round 2 passed. | `test_unresolved_findings_after_two_rounds_need_attention` (the bound) |
| 9 | "A reviewer approves the exact final version." | Sign out, sign in as **Bob Reviewer**, open the run, **Approve report v2**. Mention that an approval of v1, or a stale digest, is refused. | `test_stale_and_wrong_kind_decisions_rejected`; E2E planted-claim test |
| 10 | "Only then is it exportable as approved." | **Download approved report (v2)**: the Markdown names the approver, time and digest. A draft export is watermarked. | `test_export_is_draft_until_approved…`; `test_rejected_report_exports_only_as_draft` |

## Optional extras

| Show | How | Evidence |
| --- | --- | --- |
| Isolation between workspaces | Sign in as **Mallory Outsider** and paste Alice's run URL: "not found". | `test_other_workspace_members_get_404` (route-generated) |
| Cancellation | As Alice, submit a brief and click **Cancel run** while it waits for approval. | E2E `an analyst cancels…`; `test_cancel_retry.py` |
| Crash recovery | Stop the worker (Ctrl+C) mid-research, start it again: no duplicated tasks. | 10-point crash suite in `test_worker_recovery.py` |
| Prompt injection is data | The dev-17 corpus page orders "fetch http://169.254.169.254…". It is never fetched. | `test_llm_researcher_cites_only_collected_passages…`; evaluation `no_network_fetch_attempted` |
| Deletion and audit | As **Carol Admin**, delete a finished run; the workspace audit log still records it. | `test_admin_deletes_a_finished_run_completely…` |
| Evaluation | `python -m evaluation.run --cases dev-09,dev-17` and open the summary. | `test_evaluation.py` |

## Honesty notes for questions

- The agents in this demo are deterministic fakes. The workflow, gates, persistence,
  recovery and security are real; the *quality* of the prose is not what is being shown.
- The live-model A/B/C evaluation has not run yet: it needs an API key and budget approval.
  Fake-agent evaluation results are labelled "harness validation".
- "Approved" means a named human approved that exact version and digest. It does not mean
  the content is certified correct.
