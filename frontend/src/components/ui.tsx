import { useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import type { RunState } from "../api/types";
import { STATE_LABELS, STATE_TONES, type Tone } from "../format";

// Plain-language names for the permission in "Your role does not permit <action>".
const ACTION_WORDS: Record<string, string> = {
  "workspace.read": "open this workspace",
  "workspace.manage": "change workspace settings",
  "members.manage": "manage members",
  "run.create": "start runs",
  "run.read": "open runs",
  "run.cancel": "cancel runs",
  "run.retry": "retry runs",
  "plan.decide": "approve or reject plans",
  "report.decide": "approve or reject reports",
  "upload.create": "upload documents",
  "usage.read": "see usage",
  "data.delete": "delete data",
  "audit.read": "see the activity log",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function StateBadge({ state }: { state: RunState }) {
  return (
    <span className={`badge badge-${STATE_TONES[state]}`} data-testid="run-state">
      {STATE_LABELS[state] ?? state}
    </span>
  );
}

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted spinner" role="status">
      <span className="spinner-dot" aria-hidden="true" /> {label}
    </p>
  );
}

export function ErrorBanner({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : "Unknown error.";
  const requestId = error instanceof ApiError ? error.requestId : null;
  if (error instanceof ApiError && error.status === 403) return <ForbiddenBanner error={error} />;
  return (
    <div className="banner banner-danger" role="alert">
      <strong>{title}.</strong> {message}
      {requestId && <span className="muted small"> (request {requestId})</span>}
    </div>
  );
}

/** 403s explain what is not allowed and who can help, instead of a raw error. */
function ForbiddenBanner({ error }: { error: ApiError }) {
  const stale = /csrf|cross-origin/i.test(error.message);
  const action = /does not permit ([\w.]+)/.exec(error.message)?.[1];
  const detail = action
    ? `Your role in this workspace can't ${ACTION_WORDS[action] ?? action.replace(".", " ")}.`
    : error.message.replace(/([^.])$/, "$1.");
  return (
    <div className="banner banner-warning" role="alert" data-kind="forbidden">
      {stale ? (
        <>
          <strong>This page is out of date.</strong> Reload it and try again.
        </>
      ) : (
        <>
          <strong>Not permitted.</strong> {detail} If you need to, ask a workspace admin.
        </>
      )}
      {error.requestId && <span className="muted small"> (request {error.requestId})</span>}
    </div>
  );
}

/** A destructive action that asks first, inline. Keyboard: the confirm button takes focus,
 *  Escape backs out, and focus returns to the original button. */
export function ConfirmButton({
  label,
  prompt,
  confirmLabel,
  onConfirm,
  pending = false,
  className = "btn btn-secondary",
  ariaLabel,
}: {
  label: ReactNode;
  prompt: string;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
  className?: string;
  ariaLabel?: string;
}) {
  const [asking, setAsking] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  useEffect(() => {
    if (asking) confirmRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [asking]);
  const close = () => {
    returnFocus.current = true;
    setAsking(false);
  };

  if (!asking) {
    return (
      <button ref={triggerRef} type="button" className={className} aria-label={ariaLabel} onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  return (
    <div
      className="confirm row wrap"
      role="group"
      aria-label={prompt}
      onKeyDown={(event) => {
        if (event.key === "Escape") close();
      }}
    >
      <span className="small">{prompt}</span>
      <button type="button" className="btn btn-ghost" onClick={close}>
        Keep
      </button>
      <button
        ref={confirmRef}
        type="button"
        className="btn btn-danger"
        disabled={pending}
        onClick={() => {
          onConfirm();
          setAsking(false);
        }}
      >
        {confirmLabel}
      </button>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}
