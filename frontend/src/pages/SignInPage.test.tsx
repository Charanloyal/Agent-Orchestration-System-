import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockFetch, renderRoutes, type MockRoute } from "../test/utils";
import { SignInPage, signInNotice } from "./SignInPage";

const SIGNED_OUT: MockRoute = {
  path: "/api/v1/auth/me",
  status: 401,
  body: { error: { code: "unauthenticated", message: "Sign in required" } },
};

function render(path: string, mode: "invite" | "request" | "open", extra: MockRoute[] = []) {
  const calls = mockFetch([
    SIGNED_OUT,
    { path: "/api/v1/auth/config", body: { provider_label: "Google", signup_mode: mode } },
    ...extra,
  ]);
  const view = renderRoutes([{ path: "/signin", element: <SignInPage /> }], path);
  return { ...view, calls };
}

describe("SignInPage", () => {
  it("names the identity provider and keeps the page to return to", async () => {
    render("/signin?next=%2Fw%2Fabc%2Fruns", "invite");
    const button = await screen.findByRole("link", { name: "Continue with Google" });
    expect(button).toHaveAttribute("href", "/api/v1/auth/login?next=%2Fw%2Fabc%2Fruns");
    expect(screen.getByText(/Access is by invitation/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request access" })).toBeNull();
    expect(document.title).toContain("Sign in");
  });

  it("never offers an off-site return address", async () => {
    render("/signin?next=https%3A%2F%2Fevil.example", "open");
    expect(await screen.findByRole("link", { name: "Continue with Google" })).toHaveAttribute(
      "href",
      "/api/v1/auth/login?next=%2F",
    );
  });

  it("opens the request form for people without access and confirms the request", async () => {
    const user = userEvent.setup();
    const { calls } = render("/signin?error=not_allowed", "request", [
      { method: "POST", path: "/api/v1/access-requests", status: 202, body: { status: "received", message: "ok" } },
    ]);
    expect(await screen.findByText(/doesn't have access yet/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Work email"), "erin@example.test");
    await user.type(screen.getByLabelText("Your name"), "Erin");
    await user.type(screen.getByLabelText(/Why do you need access/), "Platform team");
    await user.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText(/Request received/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      email: "erin@example.test",
      name: "Erin",
      message: "Platform team",
    });
    expect(screen.queryByRole("button", { name: "Send request" })).toBeNull();
  });

  it("explains rate limits on access requests", async () => {
    const user = userEvent.setup();
    render("/signin", "request", [
      {
        method: "POST",
        path: "/api/v1/access-requests",
        status: 429,
        body: { error: { code: "rate_limited", message: "Too many requests; try again in 60 s" } },
      },
    ]);
    await user.click(await screen.findByRole("button", { name: "Request access" }));
    await user.type(screen.getByLabelText("Work email"), "erin@example.test");
    await user.type(screen.getByLabelText("Your name"), "Erin");
    await user.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests from your network");
  });
});

describe("signInNotice", () => {
  const errors = [
    "provider_denied",
    "provider_error",
    "provider_unavailable",
    "login_expired",
    "login_failed",
    "email_unverified",
    "not_allowed",
    "rate_limited",
  ];

  it.each(errors)("has a specific message for %s", (code) => {
    const notice = signInNotice(code, null, "Google", "invite");
    expect(notice?.text).not.toBe("Sign-in didn't complete. Try again.");
    expect(notice?.text.length).toBeGreaterThan(20);
  });

  it("names the provider where it matters", () => {
    expect(signInNotice("provider_unavailable", null, "Google", "invite")?.text).toContain("Google");
    expect(signInNotice("email_unverified", null, "Microsoft", "invite")?.text).toContain("Microsoft");
  });

  it("tells people what to do when they are not allowed in each mode", () => {
    expect(signInNotice("not_allowed", null, "Google", "request")?.text).toContain("Request access below");
    expect(signInNotice("not_allowed", null, "Google", "invite")?.text).toContain("Ask a workspace admin");
  });

  it("covers every status and falls back safely", () => {
    expect(signInNotice(null, "signed_out", "Google", "open")?.tone).toBe("success");
    expect(signInNotice(null, "session_expired", "Google", "open")?.text).toContain("Your session ended");
    expect(signInNotice(null, "access_requested", "Google", "request")?.text).toContain("Request received");
    expect(signInNotice(null, null, "Google", "open")).toBeNull();
    expect(signInNotice("something_new", null, "Google", "open")?.text).toBe("Sign-in didn't complete. Try again.");
  });
});
