import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

const SCREENSHOTS = resolve(import.meta.dirname, "..", "..", "docs", "assets", "screenshots");

/** Documentation screenshot, only when capturing them (AOS_SCREENSHOTS=1). */
export async function shot(page: Page, name: string, fullPage = true): Promise<void> {
  if (!process.env.AOS_SCREENSHOTS) return;
  mkdirSync(SCREENSHOTS, { recursive: true });
  // A sticky top bar would be stitched into the middle of a full-page capture.
  const style = fullPage ? await page.addStyleTag({ content: ".topbar { position: static !important; }" }) : null;
  await page.waitForTimeout(300); // let live updates settle
  await page.screenshot({ path: resolve(SCREENSHOTS, `${name}.png`), fullPage });
  await style?.evaluate((element) => (element as Element).remove());
}

/** Dev-issuer people (backend/devtools/dev_oidc.py). Dana and Erin are not seeded. */
export type DevUser =
  | "Alice Analyst"
  | "Bob Reviewer"
  | "Carol Admin"
  | "Mallory Outsider"
  | "Dana Newcomer"
  | "Erin Requester";

/** Sign in through the real dev identity provider and wait for the signed-in shell. */
export async function signIn(page: Page, user: DevUser): Promise<void> {
  await startSignIn(page, user);
  await expect(page.locator(".topbar .user")).toContainText(user);
}

/** Pick `user` on the dev issuer's page; the caller checks where the app sends them. */
export async function startSignIn(page: Page, user: DevUser): Promise<void> {
  await page.goto("/signin");
  await expect(page.getByTestId("api-status")).toHaveText("API available");
  await page.getByRole("link", { name: /^Continue with / }).click();
  await page.getByRole("button", { name: new RegExp(user) }).click();
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin\?status=signed_out/);
  await expect(page.getByTestId("signin-notice")).toHaveText("You have signed out.");
}

/** WCAG 2.2 A/AA checks with axe-core; the failure message lists each rule and element. */
export async function expectNoA11yViolations(page: Page, label: string): Promise<void> {
  await page.waitForLoadState("networkidle");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const problems = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.map((n) => n.target.join(" ")).join("\n    ")}`,
  );
  expect(problems, `${label}: accessibility violations`).toEqual([]);
}

/** Nothing scrolls sideways: not the page, and not any table container. */
export async function expectFitsWidth(page: Page, label: string): Promise<void> {
  await page.waitForLoadState("networkidle");
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    const wide = [...document.querySelectorAll<HTMLElement>(".table-wrap, .card, .topbar")]
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => `${el.className} (${el.scrollWidth} > ${el.clientWidth})`);
    return { page: doc.scrollWidth > window.innerWidth + 1 ? `page ${doc.scrollWidth}px` : null, wide };
  });
  expect([overflow.page, ...overflow.wide].filter(Boolean), `${label}: horizontal overflow`).toEqual([]);
}
