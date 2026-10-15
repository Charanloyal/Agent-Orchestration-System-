import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch, renderRoutes } from "../test/utils";
import { UsagePage } from "./UsagePage";

const WS = "11111111-1111-1111-1111-111111111111";

const usage = (days: number) => ({
  days,
  since: "2026-10-01T00:00:00Z",
  totals: { runs: 1, committed: "0.012300", reconciled: "0.0100", uncertain: "0.0023", llm_input_tokens: 1200,
            llm_output_tokens: 300, calls: 6 },
  by_day: [{ day: "2026-10-15", committed: "0.012300", calls: 6 }],
  by_step: [{ step: "planner", kind: "llm", calls: 1, committed: "0.0020", input_tokens: 400, output_tokens: 100 }],
  top_runs: [{ run_id: "r1", topic: "Compare tools", state: "SUCCEEDED", created_at: "2026-10-15T10:00:00Z",
               committed: "0.012300", budget: "1.00" }],
  note: "Estimated from the configured price schedule.",
});

describe("UsagePage", () => {
  it("shows estimated totals, uncertain spend, and per-run budget share; switches period", async () => {
    const calls = mockFetch([
      { path: `/api/v1/workspaces/${WS}/usage?days=30`, body: usage(30) },
      { path: `/api/v1/workspaces/${WS}/usage?days=7`, body: usage(7) },
    ]);
    renderRoutes([{ path: "w/:workspaceId/usage", element: <UsagePage /> }], `/w/${WS}/usage`);

    const committed = (await screen.findByRole("heading", { name: "Committed (estimated)" })).closest("section")!;
    expect(within(committed).getByText("$0.0123")).toBeInTheDocument();
    expect(screen.getByText("$0.0023")).toBeInTheDocument();
    expect(screen.getByText("1,500")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Compare tools" })).toHaveAttribute("href", "/runs/r1");
    expect(screen.getByText(/1\.2% of \$1\.0000/)).toBeInTheDocument();
    expect(screen.getByText(/Estimated from the configured price schedule/)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "7 days" }));
    expect(await screen.findByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
    expect(calls.map((c) => c.url)).toContain(`/api/v1/workspaces/${WS}/usage?days=7`);
  });
});
