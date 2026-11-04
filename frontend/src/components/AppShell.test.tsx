import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { RequireAuth } from "./AppShell";

const WS = "11111111-1111-1111-1111-111111111111";

function me(role: "admin" | "analyst" | "reviewer", agentMode: "fake" | "llm"): Me {
  return {
    user_id: "u1", email: "a@example.com", display_name: "Alice", csrf_token: "t",
    memberships: [{ workspace_id: WS, workspace_name: "Team", role }],
    deployment: { environment: "test", agent_mode: agentMode },
  };
}

function render(user: Me) {
  mockFetch([{ path: "/api/v1/auth/me", body: user }]);
  return renderRoutes(
    [{ element: <RequireAuth />, children: [{ path: "w/:workspaceId/runs", element: <p>runs page</p> }] }],
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
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Runs", "Documents"]);
  });

  it("gives admins the activity log", async () => {
    render(me("admin", "llm"));
    const nav = await screen.findByRole("navigation", { name: "Workspace" });
    expect(within(nav).getByRole("link", { name: "Activity" })).toHaveAttribute("href", `/w/${WS}/activity`);
  });
});
