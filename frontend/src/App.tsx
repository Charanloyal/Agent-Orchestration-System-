import { useEffect, useState } from "react";

import { fetchHealth, type HealthResponse } from "./api/health";

type HealthState =
  | { kind: "loading" }
  | { kind: "success"; data: HealthResponse }
  | { kind: "error"; message: string };

export default function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });

    fetchHealth(controller.signal)
      .then((data) => setState({ kind: "success", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const message = error instanceof Error ? error.message : "Unknown error.";
        setState({ kind: "error", message });
      });

    return () => controller.abort();
  }, [attempt]);

  return (
    <main className="page">
      <h1>Agent Orchestration System</h1>
      <p className="subtitle">Local development scaffold: backend health check</p>

      <section className="card" aria-live="polite">
        {state.kind === "loading" && <p role="status">Checking backend health…</p>}

        {state.kind === "error" && (
          <div role="alert" className="error">
            <p>
              <strong>Backend health check failed.</strong> {state.message}
            </p>
            <p>Make sure the backend is running on http://127.0.0.1:8000.</p>
          </div>
        )}

        {state.kind === "success" && (
          <>
            <p>
              Backend status: <strong data-testid="health-status">{state.data.status}</strong>
            </p>
            <p>Response body from GET /health:</p>
            <pre data-testid="health-body">{JSON.stringify(state.data)}</pre>
          </>
        )}
      </section>

      <button
        type="button"
        onClick={() => setAttempt((n) => n + 1)}
        disabled={state.kind === "loading"}
      >
        Check again
      </button>
    </main>
  );
}
