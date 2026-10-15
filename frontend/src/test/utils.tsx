import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { render } from "@testing-library/react";
import { vi } from "vitest";

export type MockRoute = { method?: string; path: string | RegExp; status?: number; body: unknown };

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
    return new Response(JSON.stringify(route.body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json", "x-request-id": "req-test" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export function renderRoutes(routes: RouteObject[], initialPath: string): ReturnType<typeof render> {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

export function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}
