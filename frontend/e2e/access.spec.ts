import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, shot, signIn, signOut, startSignIn } from "./helpers";

// The access model end to end (ADR 0021), against the real dev identity provider. The E2E
// stack runs with AOS_SIGNUP_MODE=request and Carol as the platform admin
// (playwright.config.ts). Dana and Erin exist at the identity provider but are not seeded.
// Each journey changes the shared database (an invitation used, a request decided), so a retry
// would start from the wrong state and hide the first failure: these journeys never retry.
test.describe.configure({ retries: 0 });

test("an admin invites a newcomer, who joins with the invited role on first sign-in", async ({ page }) => {
  await signIn(page, "Carol Admin");
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Workspace settings" })).toBeVisible();
  await page.getByLabel("Email address").fill("dana@example.test");
  await page.getByLabel("Role", { exact: true }).selectOption("reviewer");
  await page.getByRole("button", { name: "Invite" }).click();
  await expect(page.getByTestId("toasts")).toContainText("Invitation created for dana@example.test");
  const pending = page.getByRole("table", { name: "Pending invitations" });
  await expect(pending).toContainText("dana@example.test");
  await shot(page, "13-workspace-settings");
  await signOut(page);

  await signIn(page, "Dana Newcomer");
  await expect(page).toHaveURL(/\/w\/[0-9a-f-]{36}\/runs$/);
  await expect(page.locator(".topbar .user")).toContainText("reviewer");
  await expect(page.getByRole("link", { name: "New brief" })).toHaveCount(0);
  await signOut(page);

  await signIn(page, "Carol Admin");
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("table", { name: "Workspace members" })).toContainText("Dana Newcomer");
  await expect(page.getByText("No pending invitations.")).toBeVisible();
});

test("a stranger requests access, a platform admin approves, and they start a workspace", async ({ page }) => {
  await startSignIn(page, "Erin Requester");
  await expect(page).toHaveURL(/\/signin\?error=not_allowed/);
  await expect(page.getByTestId("signin-notice")).toContainText("doesn't have access yet");
  await page.getByLabel("Work email").fill("erin@example.test");
  await page.getByLabel("Your name").fill("Erin Requester");
  await page.getByLabel(/Why do you need access/).fill("I lead platform research.");
  await shot(page, "14-request-access");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByTestId("signin-notice")).toContainText("Request received");

  await signIn(page, "Carol Admin");
  await page.getByRole("link", { name: /^Access, 1 pending request/ }).click();
  const request = page.getByRole("list", { name: "Pending access requests" }).getByRole("listitem");
  await expect(request).toContainText("I lead platform research.");
  await shot(page, "15-access-requests");
  await request.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("toasts")).toContainText("Approved erin@example.test; they can sign in now.");
  await expect(page.getByText("No pending requests")).toBeVisible();
  await expect(page.getByRole("table", { name: "Access list" })).toContainText("erin@example.test");
  await signOut(page);

  await signIn(page, "Erin Requester");
  await expect(page.getByRole("heading", { name: "Welcome, Erin Requester" })).toBeVisible();
  await expectNoA11yViolations(page, "onboarding");
  await shot(page, "16-onboarding", false);
  await page.getByLabel("Workspace name").fill("Erin's research");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/w\/[0-9a-f-]{36}\/runs$/);
  await expect(page.locator(".topbar .user")).toContainText("admin");
});

test("an ended session sends people back to sign in, then to where they were", async ({ page, context }) => {
  await signIn(page, "Alice Analyst");
  const runs = page.url();
  await context.clearCookies();
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page).toHaveURL(/\/signin\?status=session_expired&next=%2Fw%2F/);
  await expect(page.getByTestId("signin-notice")).toContainText("Your session ended");
  await page.getByRole("link", { name: /^Continue with / }).click();
  await page.getByRole("button", { name: /Alice Analyst/ }).click();
  await expect(page).toHaveURL(/\/documents$/);
  expect(page.url().startsWith(runs.replace(/\/runs$/, ""))).toBe(true);
});
