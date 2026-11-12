import { screen, within } from "@testing-library/react";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { AgentsPage } from "./AgentsPage";

function me(agentMode: "fake" | "llm"): Me {
  return {
    user_id: "u1", email: "a@example.com", display_name: "Alice", csrf_token: "t",
    memberships: [{ workspace_id: "w1", workspace_name: "Team", role: "analyst" }],
    deployment: { environment: "test", agent_mode: agentMode },
    is_platform_admin: false, can_create_workspace: true,
  };
}

function render(user: Me) {
  mockFetch([]);
  renderRoutes(
    [{ element: <Outlet context={user} />, children: [{ path: "w/:workspaceId/agents", element: <AgentsPage /> }] }],
    "/w/w1/agents",
  );
}

describe("AgentsPage", () => {
  it("lists the four agents in pipeline order with their guards", async () => {
    render(me("fake"));
    expect(await screen.findByRole("heading", { level: 1, name: "Agents" })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Agents in pipeline order" });
    const names = within(list).getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(names).toEqual(["Planner", "Researcher", "Writer", "Reviewer"]);
    expect(screen.getByText(/at most 2 review rounds/)).toBeInTheDocument();
    expect(screen.getAllByText(/Human approval/).length).toBe(2);
  });

  it("says plainly when the deployment runs deterministic demo agents", async () => {
    render(me("fake"));
    expect(await screen.findByTestId("agent-mode")).toHaveTextContent("Deterministic demo agents");
  });

  it("names the language-model mode when live agents are configured", async () => {
    render(me("llm"));
    expect(await screen.findByTestId("agent-mode")).toHaveTextContent("Language-model agents");
  });
});
