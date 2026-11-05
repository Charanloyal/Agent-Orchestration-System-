# User guide

This guide walks through one research run from brief to approved report. The screenshots were
captured from the real application by `frontend/e2e/screenshots.spec.ts`, using the
deterministic **demo agents** (no language model). Re-capture them with
`$env:AOS_SCREENSHOTS=1; npx playwright test screenshots` from `frontend/`.

> The amber **Demo agents** badge in the top bar means the deployment uses fake agents.
> Reports then show how the workflow behaves, not how good a model's research would be.

## Roles

| Role | Can do |
| --- | --- |
| **Analyst** | Submit briefs, approve or edit plans, upload documents, cancel and retry runs, see usage |
| **Reviewer** | Read runs and evidence, approve or reject reports |
| **Admin** | Everything above, plus manage members, delete finished runs, read the activity log |

Each workspace is isolated. You see only the workspaces you belong to, and resources in other
workspaces behave as if they do not exist.

## 1. Sign in

![Sign-in page](assets/screenshots/01-sign-in.png)

Sign-in goes through your organisation's identity provider (OpenID Connect). In a pilot, only
allow-listed email addresses or domains can sign in; others see *"Your account is not invited
to this deployment"*. Locally, the dev identity provider offers the demo users Alice (analyst),
Bob (reviewer), Carol (admin) and Mallory (another workspace).

## 2. Write a brief

![New research brief form](assets/screenshots/02-new-brief.png)

**New brief** asks for:

- **Topic** and **intended audience**: who will read the report and why.
- **Research questions** (1–10): each becomes at least one research task.
- **Source policy**: which source types are allowed (public web, vendor documentation,
  uploaded documents), optional allowed or blocked domains, and an optional publication date
  floor. Agents cannot use sources outside this policy.
- **Limits**:
  - a **budget ceiling** in estimated USD (spend is reserved *before* each provider call);
  - a maximum number of tasks;
  - a deadline.

Submitting twice by accident is safe: the brief carries an idempotency key, so a double click
creates one run.

## 3. Approve the plan

![Plan awaiting approval](assets/screenshots/03-plan-awaiting-approval.png)

The planner proposes tasks, their order (tasks in the same step run in parallel), the tools
each may use, and a report outline. **Nothing is researched until an analyst approves.**

- **Approve plan vN** binds your approval to that exact version and its digest (shown as
  *Binds to digest*). If the plan changes after you opened it, the approval is refused and
  you are asked to reload.
- **Reject plan** with a comment asks the planner for a revision.
- **Edit plan** lets you change tasks directly; the edit becomes a new version that still
  needs approval.

The progress stepper at the top shows where the run is. The **Timeline** on the right updates
live and can be replayed after a page reload.

## 4. Research, drafting and automatic review

Approved tasks run in parallel. Each collected passage is stored as **evidence** with its URL,
retrieval time, publication date and a SHA-256 content hash.

![Evidence tab](assets/screenshots/06-evidence.png)

The writer drafts a report in which every statement is labelled **Fact**, **Inference**,
**Recommendation**, **Conflict** or **Unknown**, and cites evidence (`[1]`, `[2]`, ...). An
automatic reviewer then checks the draft. It verifies that the figures and wording in each
claim appear in the cited passages and, when a model is configured, checks meaning as well.
A blocking finding sends the draft back to the writer for a bounded number of rounds.

![Version 1 with a flagged claim](assets/screenshots/05-flagged-claim-in-v1.png)

In this demo, report v1 contained a planted claim with numbers that no source supports. The
reviewer flagged it as a **blocker**, and v2 removed it. The **Review** card keeps the
history of every round.

## 5. Approve the report

![Report awaiting approval with review history](assets/screenshots/04-report-with-review.png)

A reviewer (not the analyst) decides on the final report. Click any citation to see the
exact passage it relies on before approving:

![Reviewer inspecting a citation](assets/screenshots/07-reviewer-checks-citation.png)

- **Approve report vN** makes that exact version exportable.
- **Reject report** ends the run as needing attention.

Before approval, **Download draft** produces Markdown watermarked *"DRAFT - NOT APPROVED"*.
After approval, the download is the clean, approved version:

![Approved report](assets/screenshots/08-approved-report.png)

## 6. Runs, usage and activity

![Runs list](assets/screenshots/09-runs-list.png)

**Runs** lists every run in the workspace with its state. Runs waiting for a decision show
an amber badge. Waiting approvals expire after 72 hours by default; the analyst then
resubmits the brief.

![Usage page](assets/screenshots/10-usage.png)

**Usage** (analysts and admins) shows estimated and reconciled spend per run and per
provider. Amounts are estimates from configured price schedules, not a provider bill.

![Activity log](assets/screenshots/11-activity-log.png)

**Activity** (admins only) is the workspace audit log: plan and report decisions, exports,
cancellations, retries, member changes, uploads and deletions (including retention clean-ups).
Entries hold ids and counts, never report or source content. A database trigger rejects edits
and deletions, so the application cannot rewrite history. Only a database superuser could
bypass it. Entries remain after the runs they mention are deleted. Sign-in denials belong to
no workspace and are kept only in the deployment-wide audit table.

## 7. When something goes wrong

| Situation | What to do |
| --- | --- |
| Run is **Failed** | The banner names the step and reason. An analyst can press **Retry from last checkpoint** (up to 3 times); finished work is reused, not repeated. |
| Run is taking too long or is no longer needed | **Cancel run**. A run waiting for a person or in the queue is cancelled at once. A run a worker is processing stops at its next boundary (step, tool call or budget reservation); calls already in flight are still recorded. |
| Run **Needs attention** | The reviewer rejected the report, no evidence could be collected, or the budget ran out outside research. Read the timeline, adjust the brief and submit again. |
| Budget exhausted during research | Remaining tasks are not started and their questions are recorded as unresolved, so the report shows what was not covered. |
| A run must be removed | An admin can **Delete run** once it has finished (cancel it first). This permanently deletes the brief, plan, evidence, reports and exports. The activity log records the deletion. |

See [troubleshooting.md](troubleshooting.md) for setup and error-message help.

## 8. Uploaded documents

**Documents** (analysts) accepts text-based PDF, `.txt` and `.md` files up to 10 MB. The type
is decided from the file content, not from its name or the browser's declared type. Uploaded
documents are used only by briefs whose source policy allows *Uploaded documents*. The
uploader or an admin can delete an upload. Deletion removes the stored file and its
searchable text. Passages already used as evidence in a run stay with that run as part of its
immutable record, until the run itself is deleted.

## 9. Mobile and accessibility

![Run page on a phone](assets/screenshots/12-mobile-run.png)

- The interface works on narrow screens: the top bar compacts and the stepper wraps into a
  grid.
- A **Skip to content** link is the first focusable element on every page.
- Every page sets a descriptive browser title.
- Status uses text as well as colour.
- Animations respect *reduce motion*.
- All controls are reachable by keyboard; the E2E suite drives the main workflow through
  accessible names and roles.
