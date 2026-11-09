import { screen, within } from "@testing-library/react";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { ActivityPage } from "./ActivityPage";

const WS = "11111111-1111-1111-1111-111111111111";

function me(role: "admin" | "analyst"): Me {
  return {
    user_id: "u1", email: null, display_name: "Carol", csrf_token: "t",
    memberships: [{ workspace_id: WS, workspace_name: "Team", role }],
    deployment: { environment: "test", agent_mode: "fake" },
    is_platform_admin: false, can_create_workspace: true,
  };
}

function render(role: "admin" | "analyst") {
  return renderRoutes([{ element: <Outlet context={me(role)} />, children: [
    { path: "w/:workspaceId/activity", element: <ActivityPage /> },
  ] }], `/w/${WS}/activity`);
}

describe("ActivityPage", () => {
  it("renders the audit log as readable sentences for admins", async () => {
    mockFetch([{ path: `/api/v1/workspaces/${WS}/audit?limit=100`, body: [
      { id: 3, action: "run.delete", actor: "Carol Admin", target: "r1-aaaaaaaa", details: {}, created_at: "2026-11-04T10:00:00Z" },
      { id: 2, action: "run.retention_delete", actor: null, target: "r0-bbbbbbbb", details: {}, created_at: "2026-11-04T09:00:00Z" },
      { id: 1, action: "report.approve", actor: "Bob Reviewer", target: "r2-cccccccc", details: {}, created_at: "2026-11-04T08:00:00Z" },
    ] }]);
    render("admin");
    const table = await screen.findByRole("table", { name: "Workspace activity log" });
    expect(within(table).getByText("Carol Admin deleted a run")).toBeInTheDocument();
    expect(within(table).getByText("Retention removed a finished run")).toBeInTheDocument();
    expect(within(table).getByText("Bob Reviewer approved a report").closest("tr")?.querySelector("a")).toHaveAttribute(
      "href", "/runs/r2-cccccccc");
    expect(within(table).getByText("Carol Admin deleted a run").closest("tr")?.querySelector("a")).toBeNull();
    expect(document.title).toContain("Activity");
  });

  it("is admin-only", async () => {
    const calls = mockFetch([]);
    render("analyst");
    expect(await screen.findByText("Admins only")).toBeInTheDocument();
    expect(calls.length).toBe(0);
  });
});
