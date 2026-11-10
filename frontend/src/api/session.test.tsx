import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMutation, useQuery } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { Toaster } from "../components/toast";
import { ApiError } from "./client";
import { createQueryClient } from "./queryClient";
import { beginSignOut, handleUnauthorized, signInPath } from "./session";

describe("signInPath", () => {
  it("keeps only same-origin return paths", () => {
    expect(signInPath("session_expired", "/w/1/runs?x=1")).toBe(
      "/signin?status=session_expired&next=%2Fw%2F1%2Fruns%3Fx%3D1",
    );
    expect(signInPath("signed_out", "//evil.example")).toBe("/signin?status=signed_out");
    expect(signInPath(undefined, "/signin?error=x")).toBe("/signin");
  });
});

describe("handleUnauthorized", () => {
  const unauthorized = new ApiError(401, "unauthenticated", "Sign in required", null);

  it("sends people to sign in once, with the page to return to", () => {
    const navigate = vi.fn();
    const here = { pathname: "/runs/abc", search: "?tab=report" };
    expect(handleUnauthorized(unauthorized, navigate, here)).toBe(true);
    expect(handleUnauthorized(unauthorized, navigate, here)).toBe(true);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/signin?status=session_expired&next=%2Fruns%2Fabc%3Ftab%3Dreport");
  });

  it("ignores other errors and the sign-in page itself", () => {
    const navigate = vi.fn();
    expect(handleUnauthorized(new ApiError(403, "forbidden", "No", null), navigate)).toBe(false);
    expect(handleUnauthorized(unauthorized, navigate, { pathname: "/signin", search: "" })).toBe(true);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("stays quiet while someone signs out on purpose", () => {
    const navigate = vi.fn();
    beginSignOut();
    expect(handleUnauthorized(unauthorized, navigate, { pathname: "/w/1/settings", search: "" })).toBe(true);
    expect(navigate).not.toHaveBeenCalled();
  });
});

function Probe({ fail }: { fail: "query" | "mutation" }) {
  const query = useQuery({
    queryKey: ["probe"],
    queryFn: () => Promise.reject(new ApiError(401, "unauthenticated", "Sign in required", null)),
    enabled: fail === "query",
    retry: false,
  });
  const ok = useMutation({ mutationFn: () => Promise.resolve(1), meta: { success: "Saved" } });
  const bad = useMutation({
    mutationFn: () => Promise.reject(new ApiError(409, "conflict", "Already there", null)),
    meta: { error: "Could not save" },
  });
  return (
    <div>
      <button type="button" onClick={() => ok.mutate()}>ok</button>
      <button type="button" onClick={() => bad.mutate()}>bad</button>
      <span>{query.status}</span>
    </div>
  );
}

describe("createQueryClient", () => {
  it("turns mutation meta into notifications", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createQueryClient(vi.fn())}>
        <Probe fail="mutation" />
        <Toaster />
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "ok" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "bad" }));
    expect(await screen.findByText("Could not save: Already there")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Dismiss notification" })[0]!);
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("redirects to sign-in when any query finds the session gone", async () => {
    const navigate = vi.fn();
    await act(async () => {
      render(
        <QueryClientProvider client={createQueryClient(navigate)}>
          <Probe fail="query" />
        </QueryClientProvider>,
      );
    });
    await screen.findByText("error");
    expect(navigate).toHaveBeenCalledWith(expect.stringMatching(/^\/signin\?status=session_expired/));
  });
});
