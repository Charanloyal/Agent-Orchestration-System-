import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it, vi } from "vitest";

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

  it("edits a plan as a new version, dropping dependencies on removed tasks", async () => {
    const calls = renderRun("analyst", run(), [
      { method: "PUT", path: `/api/v1/runs/${RUN}/plan`, body: { ...plan, version: 2, author: "user" } },
    ]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: /Plan/ }));
    await user.click(screen.getByRole("button", { name: "Edit plan" }));
    await user.click(screen.getByRole("button", { name: "Remove task t1" }));
    await user.click(screen.getByRole("button", { name: "Save as v2" }));
    const put = calls.find((c) => c.method === "PUT");
    const body = put?.body as { base_version: number; plan: { tasks: { task_id: string; depends_on: string[] }[] } };
    expect(body.base_version).toBe(1);
    expect(body.plan.tasks).toEqual([expect.objectContaining({ task_id: "t2", depends_on: [] })]);
  });

  it("does not offer plan decisions to reviewers", async () => {
    renderRun("reviewer", run());
    expect(await screen.findByText(/Waiting for an analyst to approve plan v1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve plan/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("asks for confirmation before cancelling and shows the stopping state", async () => {
    const calls = renderRun("analyst", run({ state: "RESEARCHING", pending_decision: null }), [
      { method: "POST", path: `/api/v1/runs/${RUN}/cancel`,
        body: run({ state: "CANCEL_REQUESTED", pending_decision: null }) },
    ]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Yes, cancel run" }));
    expect(await screen.findByText(/No new steps, tool calls or model calls will start/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual([`/api/v1/runs/${RUN}/cancel`]);
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("offers a retry for failed runs", async () => {
    const calls = renderRun("analyst", run({ state: "FAILED", pending_decision: null, outcome_reason: "writer: invalid" }), [
      { method: "POST", path: `/api/v1/runs/${RUN}/retry`, body: run({ state: "WRITING", pending_decision: null }) },
    ]);
    expect(await screen.findByText(/writer: invalid/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry from last checkpoint" }));
    expect(await screen.findByTestId("run-state")).toHaveTextContent("Writing");
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/retry"))).toBe(true);
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

  it("shows review rounds, jumps to the flagged claim in the earlier version, and exports a draft", async () => {
    const section = (claims: { claim_id: string; kind: "fact" | "unknown"; text: string; evidence_ids: string[] }[]) =>
      ({ report_version: 1, plan_version: 1, sections: [{ section_id: "findings", title: "Findings", claims }] });
    const v1 = section([
      { claim_id: "f1", kind: "fact", text: "Exports run nightly.", evidence_ids: ["ev-1"] },
      { claim_id: "planted", kind: "fact", text: "It costs 37 dollars.", evidence_ids: ["ev-1"] },
    ]);
    const v2 = section([
      { claim_id: "f1", kind: "fact", text: "Exports run nightly.", evidence_ids: ["ev-1"] },
      { claim_id: "l2", kind: "unknown", text: "Removed 1 claim(s) the reviewer found unsupported.", evidence_ids: [] },
    ]);
    const detail = run({
      state: "AWAITING_REPORT_APPROVAL",
      pending_decision: { kind: "report", version: 2, digest: "d".repeat(64) },
      report: { version: 2, digest: "d".repeat(64), created_at: "2026-10-15T10:06:00Z", body: v2 },
    });
    const reviews = [
      { report_version: 1, review_round: 1, outcome: "revise", next: "WRITING", reviewed_at: "2026-10-15T10:05:00Z",
        findings: [{ finding_id: "d-num-planted", severity: "blocker", category: "unsupported_claim",
                     source: "deterministic", claim_ids: ["planted"], evidence_ids: ["ev-1"],
                     requested_action: "The figure(s) 37 do not appear in its cited passages." }] },
      { report_version: 2, review_round: 2, outcome: "pass", next: "AWAITING_REPORT_APPROVAL",
        reviewed_at: "2026-10-15T10:06:30Z", findings: [] },
    ];
    const calls = renderRun("reviewer", detail, [
      { path: `/api/v1/runs/${RUN}/reviews`, body: reviews },
      { path: `/api/v1/reports/${RUN}/versions/1`, body: { version: 1, digest: "e".repeat(64),
                                                           created_at: "2026-10-15T10:04:00Z", body: v1 } },
      { method: "POST", path: `/api/v1/reports/${RUN}/versions/2/export`, body: "# report" },
    ]);
    const user = userEvent.setup();

    const review = await screen.findByRole("heading", { name: "Review" });
    const card = review.closest("section, div.card, .card") as HTMLElement;
    expect(within(card).getByText("revision requested")).toBeInTheDocument();
    expect(within(card).getByText("passed")).toBeInTheDocument();
    expect(within(card).getByText(/automatic check/)).toBeInTheDocument();
    expect(document.getElementById("claim-planted")).toBeNull();

    await user.click(within(card).getByRole("button", { name: "planted" }));
    const flagged = await screen.findByText("It costs 37 dollars.");
    expect(flagged.closest("li")).toHaveAttribute("data-flag", "blocker");
    expect(screen.getByText("Superseded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "v2" }));
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await user.click(await screen.findByRole("button", { name: "Download draft (v2)" }));
    expect(await screen.findByTestId("export-status")).toHaveTextContent("Saved report.md");
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/versions/2/export"))).toBe(true);
    expect(click).toHaveBeenCalledOnce();
  });
});
