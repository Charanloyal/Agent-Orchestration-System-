# Project brief

- **Status:** Draft for approval. User interviews are **NOT DONE**; the problem statement is still a
  hypothesis.
- **Source:** PRD v1.2 §2. This brief narrows it to a pilot boundary and does not replace it.

## Problem hypothesis (to validate)

Analysts preparing decision briefs spend time on four things:
- splitting a question into sub-questions,
- finding evidence,
- reconciling conflicting sources,
- checking that every claim is cited.

A single generated answer hides those steps and their failures. **Not yet validated:** that this
is a real bottleneck, and that a reviewable, evidence-linked report reduces it. Validate with 3–5
interviews ([interview guide](interview-guide.md)). Do not claim time savings until a baseline
is measured.

## Pilot domain (reversible assumption)

**Technical tooling and vendor comparisons for small software teams.** Example: "Compare three
document-search approaches for a 20-person team, covering security, deployment, limitations and
public pricing." Reasons:
- public sources exist,
- conflicting and stale information is common,
- an engineer can judge the answers,
- no confidential data is needed.

Revisit after the interviews. Changing the domain means re-authoring the evaluation briefs.

## Personas

| Persona | Needs | Pilot permissions |
| --- | --- | --- |
| Analyst (primary) | Submit a brief, approve a plan, inspect evidence, get a traceable report | Create and view runs in their workspace |
| Reviewer (secondary) | Check claims against cited passages; approve or reject an exact report version | Approve reports in their workspace |
| Workspace admin | Manage members and usage limits | Manage membership and quotas |

## Pilot goals

1. A structured Markdown report in which every externally verifiable claim links to a stored
   evidence passage, and uncertainty is stated explicitly.
2. Each run is observable: status, tool activity, artifacts, and estimated versus reconciled cost.
3. Worker crashes do not duplicate committed evidence, report versions or approvals.
4. Execution is bounded by deadline, tool calls, concurrency, review rounds and budget
   reservations.
5. Measured evidence of whether the four-agent design beats a single-agent baseline. If it
   doesn't, simplify.

## Non-goals (v1)

- General assistant, visual workflow builder, arbitrary tools or code execution, browser
  automation.
- Automatic emailing or publishing, billing, scheduling, enterprise connectors, OCR or scanned
  PDFs, multi-region.
- Assuming four agents beat one.

## P0 boundary for the pilot

These are the P0 items from PRD §2.5:
- authentication and workspace RBAC,
- brief submission,
- plan and report approval,
- one search adapter with safe fetch,
- text and text-PDF ingestion,
- evidence storage and citation checking,
- report versions and Markdown export,
- durable execution with retries, cancellation and bounded revision,
- run timeline, structured logs, cost ledger and automated evaluation.

## Open decisions (owner: project lead)

| Decision | Status | Record |
| --- | --- | --- |
| Model provider | UNDECIDED | [ADR 0002](../decisions/0002-model-provider.md) |
| Search provider | UNDECIDED | [ADR 0003](../decisions/0003-search-provider.md) |
| Deployment target | UNDECIDED | [ADR 0004](../decisions/0004-deployment-target.md) |
| Development spending ceiling | UNDECIDED | [ADR 0005](../decisions/0005-spending-ceiling.md) |
| Allowed data | Proposed: public or synthetic only | [Threat model](../security/threat-model.md) |

Until these are decided, all development uses deterministic fake model and search providers,
and no paid calls are made.

## Week-1 exit gate: "a human can explain the intended report and judge a manually produced example"

The outline below is the target report shape. It was written by hand for the synthetic
evaluation case `dev-12` ("vendor does not publish enterprise pricing"). It contains **no real
vendor facts**. A reviewer should be able to say whether a report in this shape would be
acceptable, and why.

```markdown
# Enterprise pricing for <Vendor X> (synthetic example)

## Executive summary
- [UNKNOWN] No public per-seat enterprise price was found. (Sources checked: S1, S2)
- [RECOMMENDATION] Request a written quote; do not budget from third-party estimates.

## Findings
- [FACT] The pricing page lists Free and Team tiers and says "contact sales" for Enterprise. [E1]
- [FACT] The Team tier is listed at <amount> per user per month (retrieved <date>). [E2]
- [INFERENCE] Enterprise pricing is negotiated case by case. Based on E1; not stated by the vendor.

## Limitations
- Pricing pages change; every figure carries its retrieval date.
- No independent source corroborated E2.

## References
- E1: <Vendor X> pricing page, section "Enterprise". Retrieved <date>. Publication date unknown.
- E2: <Vendor X> pricing page, section "Team". Retrieved <date>.
```

**Judging checklist:**
- Is each tag (FACT, INFERENCE, RECOMMENDATION, UNKNOWN) correct?
- Does each cited passage actually support its claim?
- Is anything invented?
- Is the missing evidence stated plainly?

Record who judged the example and their verdict in the [handoff](../handoff.md).
