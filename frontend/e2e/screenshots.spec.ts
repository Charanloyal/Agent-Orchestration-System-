import { expect, test } from "@playwright/test";

import { shot, signIn, signOut } from "./helpers";

// Captures the documentation screenshots from the real, running stack (dev IdP, API, worker,
// web, Postgres) started by playwright.config.ts. Run with:  AOS_SCREENSHOTS=1 npx playwright test
// (access.spec.ts adds the access-model screenshots 13-16 in the same run).

test.use({ viewport: { width: 1360, height: 900 } });

test("capture documentation screenshots", async ({ page, browser }) => {
  test.setTimeout(180_000);
  await page.goto("/signin");
  await expect(page.getByTestId("api-status")).toHaveText("API available");
  await shot(page, "01-sign-in", false);

  await signIn(page, "Alice Analyst");
  await page.getByRole("link", { name: "New brief", exact: true }).first().click();
  await page.getByLabel("Topic").fill(
    "Compare self-hosted document search options for a 20-person software team (demo: unsupported claim)",
  );
  await page.getByLabel("Intended audience").fill("Engineering manager choosing an internal search tool");
  await page.getByLabel("Research question 1").fill("Which options can be self-hosted?");
  await page.getByRole("button", { name: "Add question" }).click();
  await page.getByLabel("Research question 2").fill("What authentication and SSO integrations does each document?");
  await shot(page, "02-new-brief");
  await page.getByRole("button", { name: "Submit brief" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting plan approval");
  await page.getByRole("tab", { name: /Plan/ }).click();
  await shot(page, "03-plan-awaiting-approval");

  await page.getByRole("button", { name: "Approve plan v1" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting report approval");
  const runUrl = page.url();
  await page.getByRole("tab", { name: /Report/ }).click();
  await expect(page.locator(".review-card")).toBeVisible();
  await shot(page, "04-report-with-review");
  await page.locator(".review-card").getByRole("button", { name: "planted" }).click();
  await expect(page.locator("#claim-planted")).toHaveAttribute("data-flag", "blocker");
  await shot(page, "05-flagged-claim-in-v1");
  await page.getByRole("tab", { name: /Evidence/ }).click();
  await shot(page, "06-evidence");

  await signOut(page);
  await signIn(page, "Bob Reviewer");
  await page.goto(runUrl);
  await page.getByRole("button", { name: /^Show evidence/ }).first().click();
  await shot(page, "07-reviewer-checks-citation");
  await page.getByRole("button", { name: /Approve report v/ }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Succeeded");
  await shot(page, "08-approved-report");
  await signOut(page);

  await signIn(page, "Carol Admin");
  await page.getByRole("link", { name: "Runs", exact: true }).click();
  await shot(page, "09-runs-list", false);
  await page.getByRole("link", { name: "Usage" }).click();
  await shot(page, "10-usage", false);
  await page.getByRole("link", { name: "Activity" }).click();
  await expect(page.getByRole("table", { name: "Workspace activity log" })).toBeVisible();
  await shot(page, "11-activity-log", false);

  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await signIn(phone, "Alice Analyst");
  await phone.goto(runUrl);
  await expect(phone.getByTestId("run-state")).toHaveText("Succeeded");
  await shot(phone, "12-mobile-run", false);
  await phone.close();

  const dark = await browser.newPage({ viewport: { width: 1360, height: 900 }, colorScheme: "dark" });
  await signIn(dark, "Bob Reviewer");
  await dark.goto(runUrl);
  await expect(dark.getByTestId("run-state")).toHaveText("Succeeded");
  await shot(dark, "17-dark-mode", false);
  await dark.close();
});
