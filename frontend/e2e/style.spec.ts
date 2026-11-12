import { expect, test } from "@playwright/test";

import { expectFitsWidth, expectNoA11yViolations, signIn } from "./helpers";

// Style studio end to end against the real API: measured values and the fact lock come from
// backend/app/services/style.py, not from fixtures.

const DRAFT =
  "It is important to note that the platform processed 1,250 requests in 2024. " +
  "Moreover, the team will delve into the results, and the review will cover every region of the network. " +
  'The CEO said "we doubled uptime to 99.9%" in March [3].';

test("a pasted draft is measured and rewritten with every fact kept", async ({ page }) => {
  await signIn(page, "Alice Analyst");
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Style studio" }).click();
  await expect(page.getByRole("heading", { name: "Style studio", level: 1 })).toBeVisible();
  await page.getByLabel("Text to measure and rewrite").fill(DRAFT);
  await page.getByRole("button", { name: "Measure and rewrite" }).click();

  const metrics = page.getByRole("region", { name: "Measurements before and after" });
  await expect(metrics).toBeVisible();
  await expect(page.getByTestId("fact-lock")).toHaveText("4 / 4");
  const rewritten = page.locator(".style-compare .card").nth(1);
  await expect(rewritten).toContainText("1,250 requests in 2024");
  await expect(rewritten).toContainText('"we doubled uptime to 99.9%"');
  await expect(rewritten).not.toContainText("delve");
  await expectNoA11yViolations(page, "style studio results");
  await page.setViewportSize({ width: 360, height: 740 });
  await expectFitsWidth(page, "style studio results");
});
