import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me } from "../api/types";
import { mockFetch, renderRoutes, type MockRoute } from "../test/utils";
import { AdminAccessPage } from "./AdminAccessPage";

function me(isPlatformAdmin: boolean): Me {
  return {
    user_id: "u1", email: "carol@example.test", display_name: "Carol", csrf_token: "t",
    memberships: [], deployment: { environment: "test", agent_mode: "fake" },
    is_platform_admin: isPlatformAdmin, can_create_workspace: true,
  };
}

const REQUEST = {
  id: "r1", email: "erin@example.test", name: "Erin", message: "I run the platform team",
  status: "pending", created_at: "2026-11-05T10:00:00Z", decided_at: null, decided_by: null,
};
const ENTRY = {
  id: "e1", email: "alice@example.test", source: "seed", note: "Demo user",
  created_at: "2026-11-01T10:00:00Z", added_by: null,
};

function render(admin: boolean, extra: MockRoute[] = [], requests = [REQUEST]) {
  const calls = mockFetch([
    ...extra,
    { path: "/api/v1/admin/access-requests?status=pending", body: requests },
    { path: "/api/v1/admin/access-requests?status=decided", body: [] },
    { path: "/api/v1/admin/workspaces", body: [{ id: "w1", name: "Demo Research Team", members: 3 }] },
    { path: "/api/v1/admin/access-list", body: [ENTRY] },
  ]);
  renderRoutes(
    [{ element: <Outlet context={me(admin)} />, children: [{ path: "admin/access", element: <AdminAccessPage /> }] }],
    "/admin/access",
  );
  return calls;
}

describe("AdminAccessPage", () => {
  it("looks like any unknown page to everyone but platform admins", async () => {
    const calls = render(false);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("approves a request into a workspace with a role", async () => {
    const user = userEvent.setup();
    const calls = render(true, [
      { method: "POST", path: "/api/v1/admin/access-requests/r1/approve", body: { status: "approved", workspace: "invited" } },
    ]);
    const list = await screen.findByRole("list", { name: "Pending access requests" });
    expect(within(list).getByText("I run the platform team")).toBeInTheDocument();
    const role = within(list).getByLabelText("Role");
    expect(role).toBeDisabled();
    await user.selectOptions(within(list).getByLabelText("Add to workspace"), "w1");
    await user.selectOptions(role, "reviewer");
    await user.click(within(list).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/they join Demo Research Team as reviewer/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ workspace_id: "w1", role: "reviewer" });
    expect(document.title).toContain("Access");
  });

  it("denies only after confirmation", async () => {
    const user = userEvent.setup();
    const calls = render(true, [
      { method: "POST", path: "/api/v1/admin/access-requests/r1/deny", status: 204, body: null },
    ]);
    await user.click(await screen.findByRole("button", { name: "Deny erin@example.test" }));
    await user.click(screen.getByRole("button", { name: "Yes, deny" }));
    expect(await screen.findByText("Denied erin@example.test.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual([
      "/api/v1/admin/access-requests/r1/deny",
    ]);
  });

  it("says when nobody is waiting", async () => {
    render(true, [], []);
    expect(await screen.findByText("No pending requests")).toBeInTheDocument();
  });

  it("adds to and removes from the access list", async () => {
    const user = userEvent.setup();
    const calls = render(true, [
      { method: "POST", path: "/api/v1/admin/access-list", status: 201, body: { ...ENTRY, id: "e2", email: "new@example.test" } },
      { method: "DELETE", path: "/api/v1/admin/access-list/e1", status: 204, body: null },
    ]);
    const table = await screen.findByRole("table", { name: "Access list" });
    expect(within(table).getByText("Demo data")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email address"), "new@example.test");
    await user.type(screen.getByLabelText(/Note/), "pilot");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Added to the access list")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "new@example.test", note: "pilot" });

    await user.click(within(table).getByRole("button", { name: "Remove access for alice@example.test" }));
    await user.click(screen.getByRole("button", { name: "Yes, remove access" }));
    expect(await screen.findByText(/signed out everywhere/)).toBeInTheDocument();
  });
});
