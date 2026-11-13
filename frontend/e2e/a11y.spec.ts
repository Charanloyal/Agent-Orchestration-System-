import { expect, test, type Page } from "@playwright/test";

import { expectFitsWidth, expectNoA11yViolations, signIn } from "./helpers";

// Accessibility (axe-core, WCAG 2.2 A/AA), dark mode, 360 px layouts and keyboard use, on
// every page of the running app. Carol is a workspace admin and the platform admin, so she
// can open every page.

async function submitBrief(page: Page): Promise<string> {
  await page.getByRole("link", { name: "New brief", exact: true }).first().click();
  const submit = page.getByRole("button", { name: "Submit brief" });
  // On a cold start the dev server may reload the page once while it optimises
  // dependencies, wiping a half-filled form: fill again until the form holds.
  await expect(async () => {
    await page.getByLabel("Topic").fill("Accessibility check brief");
    await page.getByLabel("Intended audience").fill("Testers");
    await page.getByLabel("Research question 1").fill("Is every page usable with a keyboard?");
    await expect(submit).toBeEnabled({ timeout: 1000 });
  }).toPass();
  await submit.click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting plan approval");
  return page.url();
}

async function visitAll(page: Page, runUrl: string, check: (label: string) => Promise<void>): Promise<void> {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Workspace" });
  await expect(nav).toBeVisible();
  for (const name of ["Runs", "New brief", "Documents", "Style studio", "Agents", "Usage", "Activity", "Settings"]) {
    await nav.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await check(name);
  }
  await page.goto(runUrl);
  await expect(page.getByTestId("run-state")).toBeVisible();
  await check("run");
  await page.getByRole("link", { name: /^Access/ }).click();
  await expect(page.getByRole("heading", { name: "Access", level: 1 })).toBeVisible();
  await check("access");
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await check("not found");
}

async function setTheme(page: Page, theme: "light" | "dark"): Promise<void> {
  await page.evaluate((value) => window.localStorage.setItem("aos-theme", value), theme);
}

test("every page passes axe in dark and light themes", async ({ page }) => {
  await page.goto("/signin");
  await page.getByRole("button", { name: "Request access" }).click();
  await expectNoA11yViolations(page, "sign-in (dark)");
  await setTheme(page, "light");
  await page.reload();
  await page.getByRole("button", { name: "Request access" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectNoA11yViolations(page, "sign-in (light)");

  await signIn(page, "Carol Admin");
  const runUrl = await submitBrief(page);
  await visitAll(page, runUrl, (label) => expectNoA11yViolations(page, `${label} (light)`));
  await setTheme(page, "dark");
  await visitAll(page, runUrl, (label) => expectNoA11yViolations(page, `${label} (dark)`));
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("every page fits a 360 px wide screen", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto("/signin?error=not_allowed");
  await expectFitsWidth(page, "sign-in");
  await signIn(page, "Carol Admin");
  const runUrl = await submitBrief(page);
  await visitAll(page, runUrl, (label) => expectFitsWidth(page, label));
  // Fonts differ between systems (Linux CI renders wider than Windows), so a layout that only
  // just fits at 360 px elsewhere must also fit at 320 px here.
  await page.setViewportSize({ width: 320, height: 740 });
  await visitAll(page, runUrl, (label) => expectFitsWidth(page, `${label} at 320 px`));
});

test("the app works from the keyboard", async ({ page }) => {
  await signIn(page, "Carol Admin");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();

  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Settings" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Workspace settings" })).toBeVisible();
  const remove = page.getByRole("button", { name: "Remove Alice Analyst" });
  await remove.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Yes, remove" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(remove).toBeFocused();
  await expect(page.getByRole("table", { name: "Workspace members" })).toContainText("Alice Analyst");
});
