import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { ConfirmButton, ErrorBanner } from "./ui";

describe("ErrorBanner", () => {
  it("explains missing permissions in plain words", () => {
    render(<ErrorBanner error={new ApiError(403, "forbidden", "Your role does not permit report.decide", "req-1")} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Not permitted.");
    expect(alert).toHaveTextContent("Your role in this workspace can't approve or reject reports.");
    expect(alert).toHaveTextContent("ask a workspace admin");
    expect(alert).toHaveTextContent("req-1");
  });

  it("asks for a reload when the page is stale", () => {
    render(<ErrorBanner error={new ApiError(403, "forbidden", "Missing or invalid CSRF token", null)} />);
    expect(screen.getByRole("alert")).toHaveTextContent("This page is out of date. Reload it and try again.");
  });

  it("keeps other errors as they are", () => {
    render(<ErrorBanner error={new ApiError(404, "not_found", "Not found", null)} title="Could not load this run" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load this run. Not found");
  });
});

describe("ConfirmButton", () => {
  it("confirms with the keyboard and only then acts", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmButton label="Delete" prompt="Delete it?" confirmLabel="Yes, delete" onConfirm={onConfirm} />);
    await user.tab();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("group", { name: "Delete it?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, delete" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("backs out with Escape and returns focus", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmButton label="Delete" prompt="Delete it?" confirmLabel="Yes, delete" onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
