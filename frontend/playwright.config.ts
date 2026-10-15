import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Isolated end-to-end stack: dev OIDC issuer, API, worker, and Vite, on dedicated ports and
// a dedicated database (AOS_E2E_DATABASE_URL), which global setup wipes and re-seeds.
export const BACKEND_DIR = resolve(import.meta.dirname, "..", "backend");
export const PORTS = { web: 5180, api: 8100, idp: 8101 };
export const PUBLIC_URL = `http://127.0.0.1:${PORTS.web}`;
export const ISSUER = `http://127.0.0.1:${PORTS.idp}`;

function envFile(): Record<string, string> {
  const path = join(BACKEND_DIR, ".env");
  if (!existsSync(path)) return {};
  return Object.fromEntries(
    readFileSync(path, "utf-8")
      .split(/\r?\n/)
      .filter((line) => line.includes("=") && !line.trimStart().startsWith("#"))
      .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1).trim()]),
  );
}

export const E2E_DATABASE_URL = process.env.AOS_E2E_DATABASE_URL ?? envFile().AOS_E2E_DATABASE_URL ?? "";
export const PYTHON =
  process.env.PYTHON ??
  join(BACKEND_DIR, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export const BACKEND_ENV: Record<string, string> = {
  AOS_ENV: "dev",
  AOS_DATABASE_URL: E2E_DATABASE_URL,
  AOS_PUBLIC_URL: PUBLIC_URL,
  AOS_OIDC_ISSUER: ISSUER,
  AOS_SSE_POLL_SECONDS: "0.3",
  AOS_WORKER_POLL_SECONDS: "0.3",
  AOS_LOG_JSON: "true",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: PUBLIC_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL ?? (process.env.CI ? undefined : "msedge") },
    },
  ],
  webServer: [
    {
      command: `"${PYTHON}" -m devtools.dev_oidc`,
      cwd: BACKEND_DIR,
      env: { AOS_ENV: "dev", AOS_DEV_OIDC_PORT: String(PORTS.idp), AOS_PUBLIC_URL: PUBLIC_URL },
      url: `${ISSUER}/.well-known/openid-configuration`,
      reuseExistingServer: false,
    },
    {
      command: `"${PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port ${PORTS.api}`,
      cwd: BACKEND_DIR,
      env: BACKEND_ENV,
      url: `http://127.0.0.1:${PORTS.api}/healthz`,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      env: { AOS_API_URL: `http://127.0.0.1:${PORTS.api}`, AOS_WEB_PORT: String(PORTS.web) },
      url: PUBLIC_URL,
      reuseExistingServer: false,
    },
  ],
});
