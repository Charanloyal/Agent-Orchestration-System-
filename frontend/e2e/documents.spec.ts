import { expect, test } from "@playwright/test";

test("an uploaded document is researched and cited when the brief allows only documents", async ({ page }) => {
  await page.goto("/signin");
  await page.getByRole("link", { name: "Sign in with your organization" }).click();
  await page.getByRole("button", { name: /Alice Analyst/ }).click();
  await expect(page.locator(".topbar .user")).toContainText("Alice Analyst");

  await page.getByRole("link", { name: "Documents" }).click();
  await page.getByLabel("Document file").setInputFiles({
    name: "encryption-policy.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Encryption policy\n\nAll customer data is encrypted at rest with AES-256. Keys rotate every 90 days.",
    ),
  });
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("status")).toContainText("Indexed encryption-policy.md");
  await page.getByLabel("Search documents").fill("key rotation");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.locator("blockquote").first()).toContainText("Keys rotate every 90 days");

  await page.getByRole("link", { name: "New brief", exact: true }).first().click();
  await page.getByLabel("Topic").fill("Summarize our encryption policy");
  await page.getByLabel("Intended audience").fill("Security reviewer");
  await page.getByLabel("Research question 1").fill("How often do encryption keys rotate?");
  await page.getByLabel("Public web").uncheck();
  await page.getByLabel("Vendor documentation").uncheck();
  await page.getByLabel("Uploaded documents").check();
  await page.getByRole("button", { name: "Submit brief" }).click();

  await expect(page.getByTestId("run-state")).toHaveText("Awaiting plan approval");
  await page.getByRole("tab", { name: /Plan/ }).click();
  await expect(page.getByText("search_uploads").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve plan v1" }).click();
  await expect(page.getByTestId("run-state")).toHaveText("Awaiting report approval");

  await page.getByRole("tab", { name: /Evidence/ }).click();
  await expect(page.getByText("Document", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".evidence blockquote").first()).toContainText("Keys rotate every 90 days");
});
