import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { renderRoutes } from "../test/utils";
import { NewRunPage } from "./NewRunPage";

const WS = "11111111-1111-1111-1111-111111111111";
const routes = [
  {
    element: <Outlet />,
    children: [
      { path: "w/:workspaceId/new", element: <NewRunPage /> },
      { path: "runs/:runId", element: <p>run page</p> },
    ],
  },
];

describe("NewRunPage", () => {
  it("submits a well-formed brief and reuses the idempotency key when retrying", async () => {
    const requests: { headers: Record<string, string>; body: unknown }[] = [];
    const responses = [
      new Response(JSON.stringify({ error: { code: "error", message: "temporary failure" } }), { status: 503 }),
      new Response(JSON.stringify({ id: "run-123" }), { status: 201 }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
        requests.push({ headers: init?.headers as Record<string, string>, body: JSON.parse(String(init?.body)) });
        return responses.shift()!;
      }),
    );
    const user = userEvent.setup();
    renderRoutes(routes, `/w/${WS}/new`);

    const submit = screen.getByRole("button", { name: "Submit brief" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Topic"), "Compare search tools");
    await user.type(screen.getByLabelText("Intended audience"), "Engineering manager");
    await user.type(screen.getByLabelText("Research question 1"), "Which support SSO?");
    await user.type(screen.getByLabelText("Only these domains (optional)"), "Docs.Example.com, postgresql.org");
    expect(submit).toBeEnabled();

    await user.click(submit);
    expect(await screen.findByRole("alert")).toHaveTextContent("temporary failure");
    await user.click(submit);
    await waitFor(() => expect(screen.getByText("run page")).toBeInTheDocument());

    expect(requests).toHaveLength(2);
    expect(requests[0]?.body).toMatchObject({
      workspace_id: WS,
      brief: {
        topic: "Compare search tools",
        research_questions: ["Which support SSO?"],
        source_policy: { allowed_domains: ["docs.example.com", "postgresql.org"], blocked_domains: [] },
        budget: { currency: "USD", max_estimated_cost: "2.00" },
        limits: { max_review_rounds: 2 },
      },
    });
    const [firstKey, secondKey] = requests.map((r) => r.headers["Idempotency-Key"]);
    expect(firstKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(secondKey).toBe(firstKey);
  });
});
