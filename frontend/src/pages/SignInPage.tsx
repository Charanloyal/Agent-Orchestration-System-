import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router";

import { useMe } from "../api/hooks";
import { fetchHealth } from "../api/health";
import { Spinner } from "../components/ui";

export function SignInPage() {
  const me = useMe();
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/";
  const error = params.get("error");

  if (me.isPending) return <Spinner label="Checking your session…" />;
  if (me.data) return <Navigate to={next.startsWith("/") && !next.startsWith("//") ? next : "/"} replace />;

  return (
    <div className="signin">
      <div className="signin-card">
        <span className="brand-mark large" aria-hidden="true">◆</span>
        <h1>Agent Orchestration System</h1>
        <p className="muted">
          Evidence-backed research reports, planned by agents and approved by people.
        </p>
        {error && (
          <div className="banner banner-danger" role="alert">
            Sign-in was cancelled or denied by the identity provider.
          </div>
        )}
        <a className="btn btn-primary btn-block" href={`/api/v1/auth/login?next=${encodeURIComponent(next)}`}>
          Sign in with your organization
        </a>
        <ApiStatus />
      </div>
    </div>
  );
}

function ApiStatus() {
  const [status, setStatus] = useState<"checking" | "ok" | "down">("checking");
  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then(() => setStatus("ok"))
      .catch(() => {
        if (!controller.signal.aborted) setStatus("down");
      });
    return () => controller.abort();
  }, []);
  return (
    <p className="small muted api-status" data-testid="api-status">
      <span className={`dot dot-${status}`} aria-hidden="true" />
      {status === "checking" ? "Checking API…" : status === "ok" ? "API available" : "API unavailable"}
    </p>
  );
}
