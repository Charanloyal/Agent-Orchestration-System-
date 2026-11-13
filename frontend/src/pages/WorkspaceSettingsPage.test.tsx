import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes, type MockRoute } from "../test/utils";
import { WorkspaceSettingsPage } from "./WorkspaceSettingsPage";

const WS = "11111111-1111-1111-1111-111111111111";
const BASE = `/api/v1/workspaces/${WS}`;

function me(role: "admin" | "analyst"): Me {
  return {
    user_id: "u-carol", email: "carol@example.test", display_name: "Carol", csrf_token: "t",
    memberships: [{ workspace_id: WS, workspace_name: "Team", role }],
    deployment: { environment: "test", agent_mode: "fake" },
    is_platform_admin: false, can_create_workspace: true,
  };
}

const MEMBERS = [
  { user_id: "u-alice", email: "alice@example.test", display_name: "Alice", role: "analyst" },
  { user_id: "u-carol", email: "carol@example.test", display_name: "Carol", role: "admin" },
];

const INVITATIONS = [
  {
    id: "i1", email: "dana@example.test", role: "reviewer", invited_by: "Carol",
    created_at: "2026-11-01T10:00:00Z", expires_at: "2099-11-15T10:00:00Z",
  },
  {
    id: "i2", email: "old@example.test", role: "analyst", invited_by: null,
    created_at: "2026-10-01T10:00:00Z", expires_at: "2026-10-15T10:00:00Z",
  },
];

function render(role: "admin" | "analyst", extra: MockRoute[] = []) {
  const calls = mockFetch([
    ...extra,
    { path: BASE, body: { id: WS, name: "Team", role, created_at: "2026-10-01T10:00:00Z" } },
    { path: `${BASE}/members`, body: MEMBERS },
    { path: `${BASE}/invitations`, body: INVITATIONS },
  ]);
  renderRoutes(
    [{ element: <Outlet context={me(role)} />, children: [{ path: "w/:workspaceId/settings", element: <WorkspaceSettingsPage /> }] }],
    `/w/${WS}/settings`,
  );
  return calls;
}

describe("WorkspaceSettingsPage", () => {
  it("puts the AI engine first, tests a Gemini key and saves it", async () => {
    const user = userEvent.setup();
    const demo = {
      source: "demo", live: false, label: "Deterministic demo agents", provider: null, model: null,
      key_hint: null, problem: null,
      providers: [
        {
          id: "gemini", label: "Google Gemini", models: ["gemini-4-hydrogen", "gemini-4-argon"],
          model_details: [
            { id: "gemini-4-hydrogen", label: "Gemini 4 Hydrogen", free_tier: true, thinking_levels: ["low", "medium", "high", "xhigh"] },
            { id: "gemini-4-argon", label: "Gemini 4 Argon", free_tier: false, thinking_levels: ["low", "medium", "high"] },
          ],
        },
        { id: "groq", label: "Groq", models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"] },
        { id: "openai", label: "OpenAI", models: ["gpt-4o-mini", "gpt-4o"] },
      ],
    };
    const saved = {
      ...demo, source: "workspace", live: true, label: "Google Gemini · gemini-4-hydrogen", provider: "gemini",
      model: "gemini-4-hydrogen", key_hint: "WXYZ",
    };
    const calls = render("admin", [
      { method: "PUT", path: `${BASE}/ai-config`, body: saved },
      { method: "POST", path: `${BASE}/ai-config/test`, body: { ok: true, latency_ms: 240, model: "gemini-4-hydrogen", detail: "ready" } },
      { path: `${BASE}/ai-config`, body: demo },
    ]);
    expect(await screen.findByTestId("engine-status")).toHaveTextContent("Deterministic demo fallback");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings.slice(0, 2)).toEqual(["AI engine and model provider", "Name"]);
    expect(screen.getByRole("radio", { name: /Google Gemini/ })).toBeChecked();
    const model = screen.getByRole("combobox", { name: "Model" });
    expect(model).toHaveValue("gemini-4-hydrogen");
    expect(within(model).getByRole("option", { name: "Gemini 4 Argon: gemini-4-argon (paid tier only)" })).toBeInTheDocument();
    const thinking = screen.getByRole("combobox", { name: /Thinking depth/ });
    await user.selectOptions(thinking, "xhigh");
    await user.selectOptions(model, "gemini-4-argon");
    expect(thinking).toHaveValue("");
    expect(within(thinking).queryByRole("option", { name: "xhigh" })).toBeNull();
    await user.selectOptions(model, "gemini-4-hydrogen");
    await user.selectOptions(thinking, "xhigh");

    const key = screen.getByLabelText("API key");
    expect(key).toHaveAttribute("type", "password");
    await user.type(key, "AIzaSy-test-WXYZ");
    await user.click(screen.getByRole("button", { name: "Show" }));
    expect(key).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByTestId("engine-test")).toHaveTextContent("Connected to gemini-4-hydrogen · 240 ms");
    const sent = { provider: "gemini", model: "gemini-4-hydrogen", api_key: "AIzaSy-test-WXYZ" };
    expect(calls.find((c) => c.method === "POST")?.body).toEqual(sent);

    await user.click(screen.getByRole("button", { name: "Save and use this engine" }));
    expect(await screen.findByText("Live · Google Gemini · gemini-4-hydrogen")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ ...sent, thinking_level: "xhigh" });
    expect(key).toHaveValue("");
  });

  it("is for workspace admins only", async () => {
    const calls = render("analyst");
    expect(await screen.findByText("Admins only")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("lists members with their roles and marks the current user", async () => {
    render("admin");
    const table = await screen.findByRole("table", { name: "Workspace members" });
    expect(within(table).getByText("Carol (you)")).toBeInTheDocument();
    expect(within(table).getByRole("combobox", { name: "Role for Alice" })).toHaveValue("analyst");
    expect(document.title).toContain("Workspace settings");
  });

  it("changes a role and reports the result", async () => {
    const user = userEvent.setup();
    const calls = render("admin", [
      { method: "PATCH", path: `${BASE}/members/u-alice`, body: { ...MEMBERS[0], role: "reviewer" } },
    ]);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Role for Alice" }), "reviewer");
    expect(await screen.findByText("Role updated")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ role: "reviewer" });
  });

  it("explains why the last admin cannot step down", async () => {
    const user = userEvent.setup();
    render("admin", [
      {
        method: "PATCH",
        path: `${BASE}/members/u-carol`,
        status: 409,
        body: { error: { code: "conflict", message: "A workspace must keep at least one admin" } },
      },
    ]);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Role for Carol" }), "analyst");
    expect(
      await screen.findByText("Could not change the role: A workspace must keep at least one admin"),
    ).toBeInTheDocument();
  });

  it("asks before removing a member", async () => {
    const user = userEvent.setup();
    const calls = render("admin", [{ method: "DELETE", path: `${BASE}/members/u-alice`, status: 204, body: null }]);
    await user.click(await screen.findByRole("button", { name: "Remove Alice" }));
    expect(screen.getByRole("group", { name: "Remove Alice?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, remove" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Remove Alice" })).toHaveFocus();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Remove Alice" }));
    await user.click(screen.getByRole("button", { name: "Yes, remove" }));
    expect(await screen.findByText("Member removed")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });

  it("invites by email and says what happens next", async () => {
    const user = userEvent.setup();
    const calls = render("admin", [
      {
        method: "POST",
        path: `${BASE}/invitations`,
        status: 201,
        body: { status: "invited", invitation: { ...INVITATIONS[0], email: "erin@example.test" }, member: null },
      },
    ]);
    await user.type(await screen.findByLabelText("Email address"), "erin@example.test");
    await user.selectOptions(screen.getByLabelText("Role"), "reviewer");
    await user.click(screen.getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/Invitation created for erin@example.test/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "erin@example.test", role: "reviewer" });
    expect(screen.getByLabelText("Email address")).toHaveValue("");
  });

  it("shows pending and expired invitations and revokes after confirmation", async () => {
    const user = userEvent.setup();
    const calls = render("admin", [{ method: "DELETE", path: `${BASE}/invitations/i1`, status: 204, body: null }]);
    const table = await screen.findByRole("table", { name: "Pending invitations" });
    const expired = within(table).getByText("old@example.test").closest("tr")!;
    expect(within(expired).getByText("Expired")).toBeInTheDocument();
    await user.click(within(table).getByRole("button", { name: "Revoke the invitation for dana@example.test" }));
    await user.click(screen.getByRole("button", { name: "Yes, revoke" }));
    expect(await screen.findByText("Invitation revoked")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "DELETE")?.url).toBe(`${BASE}/invitations/i1`);
  });

  it("renames the workspace only when the name changed", async () => {
    const user = userEvent.setup();
    const calls = render("admin", [
      { method: "PATCH", path: BASE, body: { id: WS, name: "Research", role: "admin", created_at: "2026-10-01T10:00:00Z" } },
    ]);
    const input = await screen.findByLabelText("Workspace name");
    await screen.findByDisplayValue("Team");
    const save = screen.getByRole("button", { name: "Save name" });
    expect(save).toBeDisabled();
    await user.clear(input);
    await user.type(input, "Research");
    await user.click(save);
    expect(await screen.findByText("Workspace renamed")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Research" });
  });
});
