# Demonstration script

Two paths, both with the **deterministic fake agents** (no model, no cost):

- **The 5-minute viva path** on the hosted app (below), for the examiners.
- **The full 10-minute local walkthrough** (further down), when a laptop demo is needed or
  the hosted app is unavailable.

Every step names the automated test that proves the same behaviour, so the demo is not the
only evidence.

## 5-minute viva path (hosted app)

**Hosted URL:** PENDING (recorded in [rehearsals.md](../operations/rehearsals.md) after the
Render deployment). Accounts: the platform admin (owner) plus one reviewer account invited
beforehand; never use examiners' personal accounts without asking.

### Pre-viva checklist (hybrid topology: the free web service sleeps after 15 idle minutes)

| When | Check |
| --- | --- |
| A week before | Render dashboard: the Postgres plan is **basic-256mb** (paid; does not expire) and billing is active through the viva (VIVA_DATE 2027-04-30). The web service is on the `main` commit you intend to show. |
| A week before | `python backend/scripts/smoke_prod.py https://<url> --expect-signup-mode request` passes. |
| 10 minutes before | Open `https://<url>/healthz` to **wake the service** (the first request after a sleep takes up to a minute). Refresh until it answers instantly. |
| 10 minutes before | Sign in as owner and as the reviewer in two browser profiles; open one finished run (for the export) and the [evaluation slide](#evaluation-slide). |
| 5 minutes before | Note the footer: `v1.0.0 · <commit>`. That is the build being shown. |

### The five minutes

| Min | Say | Do | Evidence |
| --- | --- | --- | --- |
| 0:00 | "A person signs in with Google; access is by invitation or reviewed request." | Show the sign-in page, sign in, point at the **Demo agents** badge and the footer commit. | `test_access.py`; E2E `access.spec.ts` |
| 0:30 | "An analyst writes a brief; the planner turns it into a typed plan." | **New brief** → paste the topic from [`demo_brief.json`](../../backend/app/demo_brief.json) (contains `(demo: unsupported claim)`) → submit → **Plan** tab. | `test_contract_plan.py` |
| 1:15 | "Nothing runs until a person approves this exact plan version." | Point at the digest; **Approve plan**. | `test_stale_and_wrong_kind_decisions_rejected` |
| 1:45 | "Researchers work in parallel within the budget; every claim is cited." | Timeline (two tasks at a time), **Evidence** tab, **Cost** card. | `test_fan_out_is_parallel_but_bounded…` |
| 2:30 | "The reviewer caught an invented figure; the writer revised it." | **Review** panel: round-1 blocker → click it → v1 claim highlighted → v2 has no such claim. | `test_planted_unsupported_claim_is_caught_revised_and_persisted` |
| 3:15 | **Recovery moment:** "Workers can crash; nothing is lost or repeated." | In the Render dashboard, **Restart service** while a second brief is researching; after it wakes, the run continues and the timeline shows no duplicate tasks. | `test_worker_recovery.py` (10 crash points) |
| 4:00 | "A reviewer approves the exact final version; only then is the export 'approved'." | Reviewer profile → **Approve report v2** → **Download approved report** (approver, time, digest in the file). | `test_export_is_draft_until_approved…` |
| 4:30 | "How do we know it helps? The evaluation." | Show the [evaluation slide](#evaluation-slide). | `test_evaluation.py` |

If the hosted app does not wake in time, switch to the local walkthrough below; say so.

### Evaluation slide

- Three systems on the same briefs: **A** multi-agent + reviewer, **B** single agent,
  **C** multi-agent with a pass-through reviewer; dev split (20) and a held-out split used once.
- **Measured so far (fake agents, harness validation, 30 runs per system):** outcome matches
  28/30 for each system (93%; 95% CI 79–98%); citation validity 100%; human gate never
  bypassed; injected URLs never fetched. Identical by construction: fake agents write the same
  content for A, B and C.
- **Live-model comparison: PENDING (needs owner budget)**, with the reason stated plainly. The
  harness, blind-scoring kit and kappa computation are built and tested.

## Full local walkthrough (about 10 minutes)

### Before the audience arrives

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

### The walkthrough

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

### Optional extras

| Show | How | Evidence |
| --- | --- | --- |
| Isolation between workspaces | Sign in as **Mallory Outsider** and paste Alice's run URL: "not found". | `test_other_workspace_members_get_404` (route-generated) |
| Cancellation | As Alice, submit a brief and click **Cancel run** while it waits for approval. | E2E `an analyst cancels…`; `test_cancel_retry.py` |
| Crash recovery | Stop the worker (Ctrl+C) mid-research, start it again: no duplicated tasks. | 10-point crash suite in `test_worker_recovery.py` |
| Prompt injection is data | The dev-17 corpus page orders "fetch http://169.254.169.254…". It is never fetched. | `test_llm_researcher_cites_only_collected_passages…`; evaluation `no_network_fetch_attempted` |
| Deletion and audit | As **Carol Admin**, delete a finished run; the workspace audit log still records it. | `test_admin_deletes_a_finished_run_completely…` |
| Invitation | As Carol, **Settings > Invite people**: `dana@example.test` as reviewer. Sign out; sign in as **Dana Newcomer**: she lands in the workspace as reviewer. | `test_invite_mode_refuses_strangers_and_admits_invited_people`; E2E `access.spec.ts` |
| Access request | Start the backend with `AOS_SIGNUP_MODE=request` and `AOS_PLATFORM_ADMIN_EMAILS=carol@example.test`. Sign in as **Erin Requester**: refused, with a request form. Send a request; as Carol open **Access**, approve; Erin signs in to the welcome page. | `test_platform_admin_approves_a_request_into_a_workspace`; E2E `access.spec.ts` |
| Accessibility | Switch the OS to dark mode; narrow the window to phone width; tab through a page from the skip link. | E2E `a11y.spec.ts` (axe-core, 360 px, keyboard) |
| Evaluation | `python -m evaluation.run --cases dev-09,dev-17` and open the summary. | `test_evaluation.py` |

## Honesty notes for questions

- The agents in this demo are deterministic fakes. The workflow, gates, persistence,
  recovery and security are real; the *quality* of the prose is not what is being shown.
- The live-model A/B/C evaluation has not run yet: it needs an API key and budget approval.
  Fake-agent evaluation results are labelled "harness validation".
- "Approved" means a named human approved that exact version and digest. It does not mean
  the content is certified correct.
