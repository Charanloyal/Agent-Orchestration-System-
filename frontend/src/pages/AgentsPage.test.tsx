import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { AgentsPage } from "./AgentsPage";

function me(agentMode: "fake" | "llm", model: string | null = null): Me {
  return {
    user_id: "u1", email: "a@example.com", display_name: "Alice", csrf_token: "t",
    memberships: [{ workspace_id: "w1", workspace_name: "Team", role: "analyst" }],
    deployment: { environment: "test", agent_mode: agentMode, llm_model: model, search_provider: "fake" },
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
  it("shows the workflow in order, and a step's details when it is selected", async () => {
    const user = userEvent.setup();
    render(me("fake"));
    expect(await screen.findByRole("heading", { level: 1, name: "Agents" })).toBeInTheDocument();
    const flow = screen.getByRole("list", { name: "Workflow of every run" });
    const steps = within(flow).getAllByRole("button").map((b) => b.querySelector(".flow-name")?.textContent);
    expect(steps).toEqual(["Planner", "Plan approval", "Researchers ×N", "Writer", "Reviewer", "Report approval"]);

    expect(screen.getByRole("heading", { level: 2, name: "Planner" })).toBeInTheDocument();
    expect(within(flow).getByRole("button", { name: /Planner/ })).toHaveAttribute("aria-pressed", "true");

    await user.click(within(flow).getByRole("button", { name: /Reviewer/ }));
    expect(screen.getByRole("heading", { level: 2, name: "Reviewer" })).toBeInTheDocument();
    expect(screen.getByText(/At most 2 review rounds/)).toBeInTheDocument();
    expect(screen.getByText("reviewer/v1")).toBeInTheDocument();

    await user.click(within(flow).getByRole("button", { name: /Report approval/ }));
    expect(screen.getByText("Human approval")).toBeInTheDocument();
  });

  it("says plainly when the deployment runs deterministic demo agents", async () => {
    render(me("fake"));
    expect(await screen.findByTestId("agent-mode")).toHaveTextContent("Deterministic demo agents");
    expect(screen.getByText("Deterministic demo sources")).toBeInTheDocument();
  });

  it("names the language model when live agents are configured", async () => {
    render(me("llm", "llama-3.3-70b-versatile"));
    expect(await screen.findByTestId("agent-mode")).toHaveTextContent("Language-model agents");
    expect(screen.getByText("Language model: llama-3.3-70b-versatile")).toBeInTheDocument();
  });
});
