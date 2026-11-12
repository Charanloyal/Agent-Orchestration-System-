import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes, type MockRoute } from "../test/utils";
import { HomeRedirect, RequireAuth } from "./AppShell";

const WS = "11111111-1111-1111-1111-111111111111";

function me(role: "admin" | "analyst" | "reviewer", agentMode: "fake" | "llm", extra: Partial<Me> = {}): Me {
  return {
    user_id: "u1", email: "a@example.com", display_name: "Alice", csrf_token: "t",
    memberships: [{ workspace_id: WS, workspace_name: "Team", role }],
    deployment: { environment: "test", agent_mode: agentMode },
    is_platform_admin: false, can_create_workspace: true,
    ...extra,
  };
}

function render(user: Me, routes: MockRoute[] = []) {
  mockFetch([{ path: "/api/v1/auth/me", body: user }, ...routes]);
  return renderRoutes(
    [
      {
        element: <RequireAuth />,
        children: [
          { index: true, element: <HomeRedirect /> },
          { path: "w/:workspaceId/runs", element: <p>runs page</p> },
        ],
      },
    ],
    `/w/${WS}/runs`,
  );
}

describe("AppShell", () => {
  it("starts with a skip link to the focusable main region", async () => {
    render(me("analyst", "llm"));
    await screen.findByText("runs page");
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(document.body.querySelector("a")).toBe(skip);
    expect(skip).toHaveAttribute("href", "#main");
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main");
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("labels deployments that use demo agents", async () => {
    render(me("analyst", "fake"));
    await screen.findByText("runs page");
    expect(screen.getByText("Demo agents")).toHaveAttribute("title", expect.stringContaining("not a language model"));
  });

  it("does not show the demo badge for model-backed deployments", async () => {
    render(me("analyst", "llm"));
    await screen.findByText("runs page");
    expect(screen.queryByText("Demo agents")).toBeNull();
  });

  it("shows navigation by role", async () => {
    render(me("reviewer", "llm"));
    const nav = await screen.findByRole("navigation", { name: "Workspace" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Runs", "Documents", "Agents"]);
  });

  it("gives admins the activity log and workspace settings", async () => {
    render(me("admin", "llm"));
    const nav = await screen.findByRole("navigation", { name: "Workspace" });
    expect(within(nav).getByRole("link", { name: "Activity" })).toHaveAttribute("href", `/w/${WS}/activity`);
    expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("href", `/w/${WS}/settings`);
    expect(screen.queryByRole("link", { name: /^Access/ })).toBeNull();
  });

  it("shows platform admins the access page with the number of waiting requests", async () => {
    render(me("analyst", "llm", { is_platform_admin: true }), [
      { path: "/api/v1/admin/summary", body: { pending_requests: 2 } },
    ]);
    const link = await screen.findByRole("link", { name: "Access, 2 pending requests" });
    expect(link).toHaveAttribute("href", "/admin/access");
  });

  it("names the running version and commit in the footer", async () => {
    render(me("analyst", "fake"), [
      { path: "/healthz", body: { status: "ok", version: "1.0.0", commit: "0123456789ab" } },
    ]);
    const footer = await screen.findByRole("contentinfo");
    expect(await within(footer).findByText("v1.0.0 · 0123456")).toBeInTheDocument();
  });

  it("shows only the version when the build has no commit", async () => {
    render(me("analyst", "fake"), [{ path: "/healthz", body: { status: "ok", version: "1.0.0", commit: null } }]);
    expect(await within(await screen.findByRole("contentinfo")).findByText("v1.0.0")).toBeInTheDocument();
  });
});

describe("HomeRedirect", () => {
  it("welcomes people without a workspace instead of bouncing them to sign-in", async () => {
    mockFetch([{ path: "/api/v1/auth/me", body: me("analyst", "fake", { memberships: [] }) }]);
    renderRoutes([{ element: <RequireAuth />, children: [{ index: true, element: <HomeRedirect /> }] }], "/");
    expect(await screen.findByRole("heading", { name: "Welcome, Alice" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create workspace" })).toBeDisabled();
    expect(screen.getAllByText("a@example.com", { selector: "strong" }).length).toBeGreaterThan(0);
  });
});
