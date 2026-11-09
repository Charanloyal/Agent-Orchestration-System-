import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { OnboardingPage } from "./OnboardingPage";

function me(extra: Partial<Me> = {}): Me {
  return {
    user_id: "u1", email: "dana@example.test", display_name: "Dana", csrf_token: "t",
    memberships: [], deployment: { environment: "test", agent_mode: "fake" },
    is_platform_admin: false, can_create_workspace: true, ...extra,
  };
}

function render(user: Me) {
  return renderRoutes(
    [
      {
        element: <Outlet />,
        children: [
          { index: true, element: <OnboardingPage me={user} /> },
          { path: "w/:workspaceId/runs", element: <p>runs of the new workspace</p> },
          { path: "admin/access", element: <p>access admin</p> },
        ],
      },
    ],
    "/",
  );
}

describe("OnboardingPage", () => {
  it("creates a workspace and opens it", async () => {
    const user = userEvent.setup();
    const calls = mockFetch([
      { method: "POST", path: "/api/v1/workspaces", status: 201, body: { id: "w9", name: "Research", role: "admin", created_at: "2026-11-06T10:00:00Z" } },
    ]);
    render(me());
    expect(screen.getByRole("heading", { name: "Welcome, Dana" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Workspace name"), "  Research ");
    await user.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(await screen.findByText("runs of the new workspace")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Research" });
    expect(screen.getByText("Workspace created")).toBeInTheDocument();
  });

  it("explains how to join when creating workspaces is reserved", () => {
    mockFetch([]);
    render(me({ can_create_workspace: false }));
    expect(screen.queryByRole("button", { name: "Create workspace" })).toBeNull();
    expect(screen.getByText(/Ask a workspace admin to invite/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("points platform admins to access management", async () => {
    const user = userEvent.setup();
    mockFetch([]);
    render(me({ is_platform_admin: true }));
    await user.click(screen.getByRole("link", { name: "Open access settings" }));
    expect(await screen.findByText("access admin")).toBeInTheDocument();
  });
});
