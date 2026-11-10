import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { render } from "@testing-library/react";
import { vi } from "vitest";

import { createQueryClient } from "../api/queryClient";
import { Toaster } from "../components/toast";

export type MockRoute = { method?: string; path: string | RegExp; status?: number; body: unknown; delayMs?: number };

/** Replace fetch with a table of canned JSON responses and record every request. */
export function mockFetch(routes: MockRoute[]) {
  const calls: { method: string; url: string; headers: Record<string, string>; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({
      method,
      url,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    const route = routes.find(
      (r) => (r.method ?? "GET") === method && (typeof r.path === "string" ? url === r.path : r.path.test(url)),
    );
    if (!route) return new Response(JSON.stringify({ error: { code: "not_found", message: "no mock" } }), { status: 404 });
    if (route.delayMs) await new Promise((resolve) => setTimeout(resolve, route.delayMs));
    if (route.status === 204) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(route.body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json", "x-request-id": "req-test" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

/** Render routes with the app's real query client (global feedback and 401 handling) and the
 *  toast region, without retries. `navigate` receives full-page redirects (session expiry). */
export function renderRoutes(
  routes: RouteObject[],
  initialPath: string,
  navigate: (url: string) => void = () => {},
): ReturnType<typeof render> & { router: ReturnType<typeof createMemoryRouter> } {
  const client = createQueryClient(navigate);
  client.setDefaultOptions({ queries: { retry: false } });
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  );
  return Object.assign(view, { router });
}

export function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}
