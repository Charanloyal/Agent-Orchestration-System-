import { describe, expect, it } from "vitest";

import { describeEvent } from "./format";

const event = (type: string, payload: Record<string, unknown>) => ({ id: 1, type, payload, created_at: "" });

describe("describeEvent", () => {
  it.each([
    [event("plan_proposed", { version: 2, tasks: 4 }), "Plan v2 proposed with 4 task(s)"],
    [event("state_changed", { to: "AWAITING_PLAN_APPROVAL" }), "Awaiting plan approval"],
    [event("state_changed", { to: "FAILED", reason: "planner: invalid" }), "Failed (planner: invalid)"],
    [event("decision_recorded", { kind: "report", version: 1, decision: "reject", role: "reviewer" }),
      "Report v1 rejected by reviewer"],
    [event("report_drafted", { version: 1, claims: 5, citations: 7 }), "Report v1 drafted: 5 claims, 7 citations"],
    [event("review_completed", { round: 2, report_version: 2, outcome: "insufficient_evidence", findings: {} }),
      "Review round 2 of report v2: more evidence needed"],
    [event("review_completed", { round: 1, report_version: 1, outcome: "revise",
                                 findings: { blocker: 1, major: 0, minor: 2 } }),
      "Review round 1 of report v1: revision requested (1 blocker, 2 minor)"],
    [event("report_exported", { version: 3, kind: "approved" }), "Report v3 exported as approved Markdown"],
    [event("something_new", {}), "something new"],
  ])("describes %o", (input, expected) => {
    expect(describeEvent(input)).toBe(expected);
  });
});
