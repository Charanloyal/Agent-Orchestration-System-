# Usability study: task script and record

- **Status (2026-11-06):** prepared, **blocked by owner**. It needs 5 participants (PRD
  usability gate). No sessions have been run, and no findings are claimed. The automated
  checks in [accessibility-checklist.md](accessibility-checklist.md) do not replace it.
- **Goal:** can a first-time analyst and reviewer complete the core workflow without help,
  and do they trust what they approve?
- **Format:** 45 minutes, remote or in person. Think-aloud. The facilitator does not help
  unless a participant is stuck for 2 minutes; record any help given.
- **Setup:** the hosted deployment (or a local stack) with demo agents, a fresh workspace,
  and one participant account invited as **analyst**. The facilitator signs in separately as
  **reviewer** for task 5 if the participant plays only one role. Read the consent note from
  the [interview guide](interview-guide.md) first.

## Tasks

Give each task on its own card. Do not use the interface's words (e.g. say "check the plan
the system suggests", not "approve plan v1").

| # | Task given to the participant | Success when | Watch for |
| --- | --- | --- | --- |
| 1 | "You have received an invitation to this app. Sign in and get to your team's space." | Lands on the workspace's runs page | Understanding of *Continue with Google*; reaction to the welcome page |
| 2 | "Your manager wants a short comparison of two self-hosted document search tools for a 20-person team. Ask the system to research it." | Brief submitted with topic, audience and at least one question | Which fields confuse; whether limits/budget are understood |
| 3 | "Check what the system plans to do, and let it start only if you're happy." | Plan approved (or edited and approved) | Whether *nothing is researched until approved* is understood |
| 4 | "While it works, find out what it is doing right now." | Points at the stepper or timeline | Live-update comprehension |
| 5 | "As the reviewer, decide whether the report can go to the manager. Check at least one claim against its source." | Opens a citation's evidence; approves or rejects with a reason | Whether flagged claims and the version history are noticed and trusted |
| 6 | "Download the version you would send." | Approved Markdown downloaded (not the draft) | Draft watermark noticed? |
| 7 | "A colleague needs to see this workspace as a reviewer. Give them access." (admin participants only) | Invitation created with the reviewer role | Expectation of an email being sent |

After each task: "On a scale of 1 (very hard) to 5 (very easy), how easy was that?"

## After the tasks (5 minutes)

1. SUS questionnaire (10 standard items).
2. "What would stop you from using this for real work?"
3. "Which claim in the report do you trust least, and why?"

## Record (no names; P1-P5)

| Field | P1 | P2 | P3 | P4 | P5 |
| --- | --- | --- | --- | --- | --- |
| Date, consent, recording | | | | | |
| Role played / usual job | | | | | |
| Device, browser, assistive technology | | | | | |
| Task 1 success / time / help / ease (1-5) | | | | | |
| Task 2 success / time / help / ease | | | | | |
| Task 3 success / time / help / ease | | | | | |
| Task 4 success / time / help / ease | | | | | |
| Task 5 success / time / help / ease | | | | | |
| Task 6 success / time / help / ease | | | | | |
| Task 7 success / time / help / ease | | | | | |
| SUS score | | | | | |
| Top problem (quote) | | | | | |

## Analysis and decision rule

- Report each task's completion rate as *k/n* with the exact numbers, not a percentage alone.
- Any task that 2 or more participants fail is a release blocker. Fix it, then re-test that
  task with at least 2 new participants.
- A mean SUS below 68 is below average usability. Record the three most frequent problems and
  link each to an issue.
