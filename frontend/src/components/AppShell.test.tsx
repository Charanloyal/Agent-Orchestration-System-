import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    const pill = screen.getByRole("link", { name: "Demo agents" });
    expect(pill).toHaveAttribute("title", expect.stringContaining("not a language model"));
    expect(pill).toHaveAttribute("href", `/w/${WS}/agents`);
  });

  it("names the model for model-backed deployments", async () => {
    const user = me("analyst", "llm");
    render({ ...user, deployment: { ...user.deployment, llm_model: "llama-3.3-70b-versatile" } });
    await screen.findByText("runs page");
    expect(screen.queryByText("Demo agents")).toBeNull();
    expect(screen.getByRole("link", { name: "⚡ Live · llama-3.3-70b-versatile" })).toHaveClass("engine-live");
  });

  it("shows the workspace's own engine, and sends admins to its settings", async () => {
    render(me("admin", "fake"), [
      {
        path: `/api/v1/workspaces/${WS}/ai-config`,
        body: {
          source: "workspace", live: true, label: "Google Gemini · gemini-2.5-flash", provider: "gemini",
          model: "gemini-2.5-flash", key_hint: "WXYZ", problem: null, providers: [],
        },
      },
    ]);
    const pill = await screen.findByRole("link", { name: "⚡ Live · gemini-2.5-flash" });
    expect(pill).toHaveAttribute("href", `/w/${WS}/settings#ai-engine`);
  });

  it("switches the colour theme: dark by default, then light, then the system's", async () => {
    const userEvents = userEvent.setup();
    window.localStorage.removeItem("aos-theme");
    render(me("analyst", "fake"));
    await screen.findByText("runs page");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await userEvents.click(screen.getByRole("button", { name: "Colour theme: Dark. Switch to Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("aos-theme")).toBe("light");
    await userEvents.click(screen.getByRole("button", { name: "Colour theme: Light. Switch to System" }));
    expect(window.localStorage.getItem("aos-theme")).toBe("system");
    window.localStorage.removeItem("aos-theme");
  });

  it("shows navigation by role", async () => {
    render(me("reviewer", "llm"));
    const nav = await screen.findByRole("navigation", { name: "Workspace" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Runs",
      "Documents",
      "Style studio",
      "Agents",
    ]);
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
