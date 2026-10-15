import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import type { RunState } from "../api/types";
import { STATE_LABELS, STATE_TONES, type Tone } from "../format";

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
  return (
    <div className="banner banner-danger" role="alert">
      <strong>{title}.</strong> {message}
      {requestId && <span className="muted small"> (request {requestId})</span>}
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
