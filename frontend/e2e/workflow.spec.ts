import { readFile } from "node:fs/promises";

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

  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download approved report (v1)" }).click();
  const file = await downloading;
  expect(file.suggestedFilename()).toMatch(/^report-[0-9a-f]{8}-v1-approved\.md$/);
  const markdown = await readFile(await file.path(), "utf-8");
  expect(markdown).toContain("Approved by Bob Reviewer");
  expect(markdown).toContain("## Sources");
  expect(markdown).not.toContain("DRAFT - NOT APPROVED");
  await expect(page.getByTestId("export-status")).toContainText("(approved)");
  // The stream of a finished run has closed; reloading replays the persisted export event.
  await page.reload();
  await expect(page.getByText(/Report v1 exported as approved Markdown/)).toBeVisible();
});

test("the reviewer catches a planted unsupported figure and the writer revises it", async ({ page }) => {
  await signIn(page, "Alice Analyst");
  await page.getByRole("link", { name: "New brief", exact: true }).first().click();
  await page.getByLabel("Topic").fill("Backup tooling options (demo: unsupported claim)");
  await page.getByLabel("Intended audience").fill("Platform team");
  await page.getByLabel("Research question 1").fill("Which tools support point-in-time recovery?");
  await page.getByRole("button", { name: "Submit brief" }).click();

  await expect(page.getByTestId("run-state")).toHaveText("Awaiting plan approval");
  await page.getByRole("button", { name: "Approve plan v1" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting report approval");
  await expect(page.getByText(/Review round 1 of report v1: revision requested \(1 blocker\)/)).toBeVisible();

  const review = page.locator(".review-card");
  await expect(review.getByTestId("finding")).toContainText("37");
  await expect(review.getByText("passed")).toBeVisible();
  await expect(page.getByText(/37 dollars/)).toHaveCount(0);

  await review.getByRole("button", { name: "planted" }).click();
  await expect(page.locator("#claim-planted")).toHaveAttribute("data-flag", "blocker");
  await expect(page.getByText("Superseded")).toBeVisible();

  await page.getByRole("button", { name: "v2" }).click();
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download draft (v2)" }).click();
  const markdown = await readFile(await (await downloading).path(), "utf-8");
  expect(markdown.startsWith("> **DRAFT - NOT APPROVED.**")).toBe(true);
  expect(markdown).not.toContain("37 dollars");
});

test("an analyst cancels a run that is waiting for plan approval", async ({ page }) => {
  await signIn(page, "Alice Analyst");
  await page.getByRole("link", { name: "New brief", exact: true }).first().click();
  await page.getByLabel("Topic").fill("A brief that will be cancelled");
  await page.getByLabel("Intended audience").fill("Nobody");
  await page.getByLabel("Research question 1").fill("Is cancellation immediate while waiting?");
  await page.getByRole("button", { name: "Submit brief" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting plan approval");

  await page.getByRole("button", { name: "Cancel run" }).click();
  await page.getByRole("button", { name: "Yes, cancel run" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Cancelled");
  await expect(page.getByRole("button", { name: "Approve plan v1" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel run" })).toHaveCount(0);
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
