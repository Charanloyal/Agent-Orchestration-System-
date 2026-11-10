import { ApiError } from "./client";

export type SignInStatus = "signed_out" | "session_expired" | "access_requested";

/** Sign-in page URL with an optional status banner and a same-origin return path. */
export function signInPath(status?: SignInStatus, next?: string): string {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/signin") && next !== "/") {
    params.set("next", next);
  }
  const query = params.toString();
  return query ? `/signin?${query}` : "/signin";
}

let redirecting = false;

/** A 401 from any request after sign-in means the session ended (it expired, was revoked, or
 *  the person signed out in another tab). Leave for the sign-in page once, keeping the
 *  current page so sign-in can return to it. Returns true when the error was a 401. */
export function handleUnauthorized(
  error: unknown,
  navigate: (url: string) => void = (url) => window.location.assign(url),
  here: Pick<Location, "pathname" | "search"> = window.location,
): boolean {
  if (!(error instanceof ApiError) || error.status !== 401) return false;
  if (redirecting || here.pathname.startsWith("/signin")) return true;
  redirecting = true;
  navigate(signInPath("session_expired", here.pathname + here.search));
  return true;
}

/** Signing out on purpose: requests that fail with 401 meanwhile are expected, so they must
 *  not turn the sign-out into a "session ended" redirect. */
export function beginSignOut(): void {
  redirecting = true;
}

/** Test hook: allow another redirect. */
export function resetUnauthorizedGuard(): void {
  redirecting = false;
}
