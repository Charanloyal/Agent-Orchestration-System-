import { useSyncExternalStore } from "react";

// Notifications for completed actions. A tiny external store, so mutation callbacks outside
// React (the global MutationCache) can raise them too. Successes are announced politely,
// errors assertively; both regions exist before any message arrives, as screen readers need.

export type ToastTone = "success" | "error" | "info";
export type ToastItem = { id: number; tone: ToastTone; message: string };

const MAX_VISIBLE = 4;
let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify(tone: ToastTone, message: string, timeoutMs = tone === "error" ? 9000 : 5000): number {
  const id = nextId++;
  items = [...items.slice(-(MAX_VISIBLE - 1)), { id, tone, message }];
  emit();
  if (timeoutMs > 0) setTimeout(() => dismiss(id), timeoutMs);
  return id;
}

export function dismiss(id: number): void {
  items = items.filter((toast) => toast.id !== id);
  emit();
}

export function clearToasts(): void {
  items = [];
  emit();
}

function Toast({ toast }: { toast: ToastItem }) {
  return (
    <div className={`toast toast-${toast.tone}`}>
      <span className="toast-icon" aria-hidden="true">
        {toast.tone === "success" ? "✓" : toast.tone === "error" ? "!" : "i"}
      </span>
      <span className="toast-message">{toast.message}</span>
      <button type="button" className="toast-close" aria-label="Dismiss notification" onClick={() => dismiss(toast.id)}>
        ×
      </button>
    </div>
  );
}

export function Toaster() {
  const toasts = useSyncExternalStore(subscribe, () => items);
  // Plain live regions (no alert/status role): page-level alerts stay unambiguous.
  return (
    <div className="toast-stack" data-testid="toasts">
      <div aria-live="polite" className="toast-region">
        {toasts.filter((t) => t.tone !== "error").map((t) => (
          <Toast key={t.id} toast={t} />
        ))}
      </div>
      <div aria-live="assertive" className="toast-region">
        {toasts.filter((t) => t.tone === "error").map((t) => (
          <Toast key={t.id} toast={t} />
        ))}
      </div>
    </div>
  );
}
