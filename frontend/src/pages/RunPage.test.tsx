import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me, RunDetail } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { RunPage } from "./RunPage";

const WS = "11111111-1111-1111-1111-111111111111";
const RUN = "22222222-2222-2222-2222-222222222222";

function me(role: "analyst" | "reviewer"): Me {
  return {
    user_id: "u1", email: "u@example.test", display_name: "U", csrf_token: "t",
    memberships: [{ workspace_id: WS, workspace_name: "Team", role }],
  };
}

const plan = {
  version: 1, digest: "a".repeat(64), created_at: "2026-10-15T10:00:00Z",
  body: {
    plan_version: 1, source_strategy: "Vendor docs first.", assumptions: [],
    outline: [{ section_id: "summary", title: "Summary", purpose: "Answer" }],
    tasks: [
      { task_id: "t1", question: "Q1", depends_on: [], tools: ["web_search"], expected_evidence: "e", section_ids: ["summary"] },
      { task_id: "t2", question: "Q2", depends_on: ["t1"], tools: ["web_search"], expected_evidence: "e", section_ids: ["summary"] },
    ],
  },
};

function run(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: RUN, workspace_id: WS, state: "AWAITING_PLAN_APPROVAL", topic: "Compare search tools",
    created_by: "Ana", created_at: "2026-10-15T10:00:00Z", updated_at: "2026-10-15T10:00:00Z",
    brief: { audience: "Managers" } as RunDetail["brief"], deadline_at: "2026-10-15T11:00:00Z", outcome_reason: null,
    job: { state: "WAITING", waiting_for: "plan", attempts: 0, wait_deadline_at: null, last_error: null },
    pending_decision: { kind: "plan", version: 1, digest: "a".repeat(64) },
    plan, report: null, decisions: [], ...overrides,
  };
}

function renderRun(role: "analyst" | "reviewer", detail: RunDetail, extra: Parameters<typeof mockFetch>[0] = []) {
  const calls = mockFetch([{ path: `/api/v1/runs/${RUN}`, body: detail }, ...extra]);
  renderRoutes([{ element: <Outlet context={me(role)} />, children: [{ path: "runs/:runId", element: <RunPage /> }] }],
               `/runs/${RUN}`);
  return calls;
}

describe("RunPage", () => {
  it("lets an analyst approve the exact pending plan version and digest", async () => {
    const calls = renderRun("analyst", run(), [
      { method: "POST", path: `/api/v1/runs/${RUN}/plan-decisions`, status: 201, body: { id: "d1" } },
    ]);
    const approve = await screen.findByRole("button", { name: "Approve plan v1" });
    await userEvent.setup().click(approve);
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ version: 1, digest: "a".repeat(64), decision: "approve" });
    expect(screen.getByText("Q2").closest("li")).toHaveTextContent("needs t1");
  });

  it("does not offer plan decisions to reviewers", async () => {
    renderRun("reviewer", run());
    expect(await screen.findByText(/Waiting for an analyst to approve plan v1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve plan/ })).not.toBeInTheDocument();
  });

  it("renders claims with kinds and opens cited evidence; unsafe URLs are not linked", async () => {
    const detail = run({
      state: "AWAITING_REPORT_APPROVAL",
      pending_decision: { kind: "report", version: 1, digest: "b".repeat(64) },
      report: {
        version: 1, digest: "b".repeat(64), created_at: "2026-10-15T10:05:00Z",
        body: { report_version: 1, plan_version: 1, sections: [{ section_id: "summary", title: "Summary", claims: [
          { claim_id: "c1", kind: "fact", text: "Tool A supports SSO.", evidence_ids: ["ev-1"] },
          { claim_id: "c2", kind: "unknown", text: "Pricing is not public.", evidence_ids: [] },
        ] }] },
      },
    });
    renderRun("reviewer", detail, [{
      path: `/api/v1/runs/${RUN}/evidence`,
      body: [{ evidence_id: "ev-1", task_id: "t1", locator: "passage 1", text: "SSO via SAML is supported.",
               text_sha256: "c".repeat(64), source_id: "src-1", source_title: "Malicious page", source_kind: "web",
               source_url: "javascript:alert(1)", published_on: null, retrieved_at: "2026-10-15T10:01:00Z" }],
    }]);

    expect(await screen.findByText("Tool A supports SSO.")).toBeInTheDocument();
    expect(screen.getByText("Fact")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve report v1" })).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Show evidence ev-1" }));
    const panel = await screen.findByRole("complementary", { name: "Cited evidence" });
    expect(await within(panel).findByText("SSO via SAML is supported.")).toBeInTheDocument();
    expect(within(panel).getByText("Malicious page").closest("a")).toBeNull();
    expect(within(panel).getByText(/publication date unknown/)).toBeInTheDocument();
  });
});
