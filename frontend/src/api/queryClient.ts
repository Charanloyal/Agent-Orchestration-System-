import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { notify } from "../components/toast";
import { ApiError } from "./client";
import { handleUnauthorized } from "./session";

declare module "@tanstack/react-query" {
  interface Register {
    /** Feedback for a mutation: `success` is shown when it completes; `error` prefixes the
     *  server's message when it fails (omit it where the page shows the error inline). */
    mutationMeta: { success?: string; error?: string };
  }
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Unknown error.";
}

export function createQueryClient(navigate?: (url: string) => void): QueryClient {
  const unauthorized = (error: unknown) => handleUnauthorized(error, navigate);
  return new QueryClient({
    queryCache: new QueryCache({ onError: (error) => void unauthorized(error) }),
    mutationCache: new MutationCache({
      onSuccess: (_data, _variables, _context, mutation) => {
        if (mutation.meta?.success) notify("success", mutation.meta.success);
      },
      onError: (error, _variables, _context, mutation) => {
        if (unauthorized(error)) return;
        if (mutation.meta?.error) notify("error", `${mutation.meta.error}: ${errorText(error)}`);
      },
    }),
    defaultOptions: {
      queries: {
        // Retry transient failures only; 4xx responses are definitive.
        retry: (failureCount, error) =>
          failureCount < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
        refetchOnWindowFocus: true,
      },
    },
  });
}
