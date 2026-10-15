import { describe, expect, it } from "vitest";

import { api, ApiError, setCsrfToken } from "./client";
import { mockFetch } from "../test/utils";

describe("api client", () => {
  it("returns parsed JSON for successful responses", async () => {
    mockFetch([{ path: "/api/v1/thing", body: { ok: true } }]);
    await expect(api("/api/v1/thing")).resolves.toEqual({ ok: true });
  });

  it("turns the error envelope into an ApiError with code and request id", async () => {
    mockFetch([
      {
        path: "/api/v1/thing",
        status: 409,
        body: { error: { code: "conflict", message: "Stale decision", request_id: "abc123" } },
      },
    ]);
    const error = await api("/api/v1/thing").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "conflict", message: "Stale decision", requestId: "abc123" });
  });

  it("sends the CSRF token on unsafe methods only", async () => {
    const calls = mockFetch([
      { path: "/api/v1/a", body: {} },
      { method: "POST", path: "/api/v1/a", body: {} },
    ]);
    setCsrfToken("csrf-token-value");
    await api("/api/v1/a");
    await api("/api/v1/a", { method: "POST", body: { x: 1 } });
    expect(calls[0]?.headers["X-CSRF-Token"]).toBeUndefined();
    expect(calls[1]?.headers["X-CSRF-Token"]).toBe("csrf-token-value");
    expect(calls[1]?.body).toEqual({ x: 1 });
    setCsrfToken(null);
  });

  it("reports network failures without leaking internals", async () => {
    const original = globalThis.fetch;
    globalThis.fetch = (() => Promise.reject(new TypeError("Failed to fetch"))) as typeof fetch;
    await expect(api("/api/v1/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
    globalThis.fetch = original;
  });
});
