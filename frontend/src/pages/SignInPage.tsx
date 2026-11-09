import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { fetchHealth } from "../api/health";
import { useAuthConfig, useDocumentTitle, useMe, useRequestAccess } from "../api/hooks";
import { signInPath } from "../api/session";
import type { SignupMode } from "../api/types";
import { Spinner } from "../components/ui";

type Notice = { tone: "danger" | "warning" | "info" | "success"; text: string };

/** Every `error` the server can send back (app/api/auth.py) and every `status` the app uses. */
export function signInNotice(
  error: string | null,
  status: string | null,
  provider: string,
  mode: SignupMode | undefined,
): Notice | null {
  switch (error) {
    case null:
      break;
    case "provider_denied":
      return { tone: "warning", text: `Sign-in was cancelled at ${provider}. Try again when you're ready.` };
    case "provider_error":
      return { tone: "danger", text: `${provider} reported a problem with this sign-in. Try again in a moment.` };
    case "provider_unavailable":
      return { tone: "danger", text: `We couldn't reach ${provider}. Try again in a minute.` };
    case "login_expired":
      return {
        tone: "warning",
        text: "That sign-in attempt expired or was started in another tab or browser. Start again here.",
      };
    case "login_failed":
      return {
        tone: "danger",
        text: `We couldn't verify the response from ${provider}. Start again; if it keeps happening, tell your administrator.`,
      };
    case "email_unverified":
      return {
        tone: "danger",
        text: `${provider} did not confirm an email address for this account. Use an account with a verified email.`,
      };
    case "not_allowed":
      return mode === "request"
        ? { tone: "warning", text: "This account doesn't have access yet. Request access below and an administrator will review it." }
        : { tone: "warning", text: "This account isn't invited yet. Ask a workspace admin to invite your email address, then sign in again." };
    case "rate_limited":
      return { tone: "warning", text: "Too many sign-in attempts from your network. Wait a few minutes, then try again." };
    default:
      return { tone: "danger", text: "Sign-in didn't complete. Try again." };
  }
  switch (status) {
    case "signed_out":
      return { tone: "success", text: "You have signed out." };
    case "session_expired":
      return { tone: "info", text: "Your session ended. Sign in again to pick up where you left off." };
    case "access_requested":
      return {
        tone: "success",
        text: "Request received. An administrator reviews it; once approved, sign in with the same email address.",
      };
    default:
      return null;
  }
}

export function SignInPage() {
  useDocumentTitle("Sign in");
  const me = useMe();
  const config = useAuthConfig();
  const [params] = useSearchParams();
  const rawNext = params.get("next") ?? "/";
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";
  const error = params.get("error");
  const provider = config.data?.provider_label ?? "your organization";
  const mode = config.data?.signup_mode;
  const notice = signInNotice(error, params.get("status"), provider, mode);

  if (me.isPending) return <Spinner label="Checking your session…" />;
  if (me.data) return <Navigate to={next} replace />;

  return (
    <div className="signin">
      <main className="signin-card" id="main">
        <span className="brand-mark large" aria-hidden="true">
          ◆
        </span>
        <h1>Agent Orchestration System</h1>
        <p className="muted">Evidence-backed research reports, planned by agents and approved by people.</p>
        {notice && (
          <div
            className={`banner banner-${notice.tone}`}
            role={notice.tone === "danger" || notice.tone === "warning" ? "alert" : "status"}
            data-testid="signin-notice"
          >
            {notice.text}
          </div>
        )}
        <a className="btn btn-primary btn-block" href={`/api/v1/auth/login?next=${encodeURIComponent(next)}`}>
          Continue with {provider}
        </a>
        {mode === "request" && params.get("status") !== "access_requested" && (
          <RequestAccess open={error === "not_allowed"} />
        )}
        {mode === "invite" && (
          <p className="small muted">New here? Access is by invitation: ask a workspace admin to invite you.</p>
        )}
        <ApiStatus />
      </main>
    </div>
  );
}

function RequestAccess({ open }: { open: boolean }) {
  const request = useRequestAccess();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [shown, setShown] = useState(open);

  if (!shown) {
    return (
      <p className="small muted">
        No access yet?{" "}
        <button type="button" className="link-button" onClick={() => setShown(true)}>
          Request access
        </button>
      </p>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    request.mutate(
      { email: email.trim(), name: name.trim(), message: message.trim() || undefined },
      { onSuccess: () => navigate(signInPath("access_requested"), { replace: true }) },
    );
  };
  const problem =
    request.error instanceof ApiError && request.error.status === 429
      ? "Too many requests from your network. Try again later."
      : request.error instanceof ApiError && request.error.status === 422
        ? "Check the email address and name, then try again."
        : request.error
          ? request.error.message
          : null;

  return (
    <form className="request-access" onSubmit={submit} aria-labelledby="request-access-title">
      <h2 id="request-access-title">Request access</h2>
      <p className="small muted">
        Use the email address you sign in with. An administrator reviews each request; you'll be able to sign
        in once it's approved.
      </p>
      <label className="field">
        <span>Work email</span>
        <input
          type="email"
          autoComplete="email"
          required
          maxLength={320}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label className="field">
        <span>Your name</span>
        <input autoComplete="name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span>
          Why do you need access? <span className="muted">(optional)</span>
        </span>
        <textarea rows={3} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      {problem && (
        <p className="validation" role="alert">
          {problem}
        </p>
      )}
      <button type="submit" className="btn btn-secondary btn-block" disabled={request.isPending}>
        {request.isPending ? "Sending…" : "Send request"}
      </button>
    </form>
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
