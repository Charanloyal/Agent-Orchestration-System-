import { expect, test, type Page } from "@playwright/test";

type DemoUser = "Alice Analyst" | "Bob Reviewer" | "Mallory Outsider";

async function signIn(page: Page, user: DemoUser): Promise<void> {
  await page.goto("/signin");
  await expect(page.getByTestId("api-status")).toHaveText("API available");
  await page.getByRole("link", { name: "Sign in with your organization" }).click();
  await page.getByRole("button", { name: new RegExp(user) }).click();
  await expect(page.locator(".topbar .user")).toContainText(user);
}

async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin/);
}

test("analyst submits a brief and approves the plan; reviewer approves the cited report", async ({ page }) => {
  await signIn(page, "Alice Analyst");
  await page.getByRole("link", { name: "New brief", exact: true }).first().click();

  await page.getByLabel("Topic").fill("Compare self-hosted document search options");
  await page.getByLabel("Intended audience").fill("Engineering manager");
  await page.getByLabel("Research question 1").fill("Which options can be self-hosted?");
  await page.getByRole("button", { name: "Add question" }).click();
  await page.getByLabel("Research question 2").fill("Which options document SSO support?");
  await page.getByRole("button", { name: "Submit brief" }).click();

  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
  const runUrl = page.url();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting plan approval");
  await expect(page.getByText("Plan v1 proposed with 3 task(s)")).toBeVisible();

  await page.getByRole("button", { name: "Approve plan v1" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting report approval");
  await expect(page.getByText(/Waiting for a reviewer to approve report v1/)).toBeVisible();

  // Reloading reconnects the event stream and replays the persisted timeline.
  await page.reload();
  await expect(page.getByText("Plan v1 approved by analyst")).toBeVisible();
  await expect(page.getByText(/Report v1 drafted/)).toBeVisible();
  await signOut(page);

  await signIn(page, "Bob Reviewer");
  await page.goto(runUrl);
  await expect(page.getByRole("button", { name: "Approve report v1" })).toBeVisible();
  await page.getByRole("button", { name: /^Show evidence/ }).first().click();
  const panel = page.getByRole("complementary", { name: "Cited evidence" });
  await expect(panel.locator("blockquote")).toContainText("Synthetic documentation page");

  await page.getByRole("button", { name: "Approve report v1" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Succeeded");
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  await expect(page.getByTestId("stream-status")).toHaveText("Finished");
});

test("a member of another workspace cannot open the run", async ({ page }) => {
  await signIn(page, "Alice Analyst");
  const firstRun = page.getByRole("table").getByRole("link").first();
  await expect(firstRun).toBeVisible();
  const href = await firstRun.getAttribute("href");
  await signOut(page);

  await signIn(page, "Mallory Outsider");
  await page.goto(href!);
  await expect(page.getByRole("alert")).toContainText("Could not load this run");
  await expect(page.getByRole("alert")).toContainText("Not found");
});
