import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router";

import { useAiEngine, useRemoveAiEngine, useSaveAiEngine, useTestAiEngine } from "../api/hooks";
import type { AiEngine, AiProviderId, ThinkingLevel } from "../api/types";
import { Card, ConfirmButton, ErrorBanner, Spinner } from "./ui";

const KEY_HINTS: Record<AiProviderId, string> = {
  gemini: "Paste a Google AI Studio key (starts with AIza…)",
  groq: "Paste a Groq key (starts with gsk_…)",
  openai: "Paste an OpenAI key (starts with sk-…)",
};

export function engineSourceText(engine: AiEngine): string {
  if (engine.source === "workspace") return `This workspace's own key (ending ${engine.key_hint})`;
  if (engine.source === "environment") return "The deployment's key, set on the server";
  return "No key yet: runs and rewrites use the deterministic demo agents";
}

/** Workspace admins choose the model engine for this workspace's runs and style rewrites
 *  (ADR 0029). The key is encrypted on the server and never shown again. */
export function AiEngineCard({ workspaceId }: { workspaceId: string }) {
  const engine = useAiEngine(workspaceId);
  const save = useSaveAiEngine(workspaceId);
  const test = useTestAiEngine(workspaceId);
  const remove = useRemoveAiEngine(workspaceId);
  const location = useLocation();
  const ref = useRef<HTMLDivElement>(null);
  const ids = useId();
  const [provider, setProvider] = useState<AiProviderId>("gemini");
  const [model, setModel] = useState("gemini-4-hydrogen");
  const [thinking, setThinking] = useState<ThinkingLevel | "">("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    const data = engine.data;
    if (data?.source === "workspace" && data.provider && data.model) {
      setProvider(data.provider as AiProviderId);
      setModel(data.model);
      setThinking(data.thinking_level ?? "");
    }
  }, [engine.data]);
  useEffect(() => {
    if (location.hash === "#ai-engine" && ref.current) {
      ref.current.scrollIntoView({ block: "start" });
      ref.current.querySelector("h2")?.focus();
    }
  }, [location.hash, engine.isSuccess]);

  if (engine.isPending) return <Spinner label="Loading the engine…" />;
  if (engine.isError) return <ErrorBanner error={engine.error} title="Could not load the engine" />;
  const data = engine.data;
  const current = data.providers.find((p) => p.id === provider);
  const models = current?.models ?? [];
  const details = current?.model_details ?? [];
  const levels = details.find((d) => d.id === model)?.thinking_levels ?? [];
  const keepsKey = data.source === "workspace" && data.provider === provider;
  const pickModel = (next: string) => {
    setModel(next);
    const allowed = current?.model_details?.find((d) => d.id === next)?.thinking_levels ?? [];
    if (thinking && !allowed.includes(thinking)) setThinking("");
    test.reset();
  };
  const choose = (next: AiProviderId) => {
    setProvider(next);
    setModel(data.providers.find((p) => p.id === next)?.models[0] ?? "");
    setThinking("");
    test.reset();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(
      { provider, model, api_key: apiKey.trim() || undefined, thinking_level: thinking || null },
      { onSuccess: () => setApiKey("") },
    );
  };
  const runTest = () =>
    test.mutate(apiKey.trim() ? { provider, model, api_key: apiKey.trim() } : {});

  return (
    <div id="ai-engine" ref={ref} className="ai-engine">
      <Card
        title="AI engine and model provider"
        className="ai-engine-card"
        actions={
          <span className={`engine-pill ${data.live ? "engine-live" : "engine-demo"}`} data-testid="engine-status">
            <span className="engine-dot" aria-hidden="true" />
            <span className="engine-label">{data.live ? `Live · ${data.label}` : "Deterministic demo fallback"}</span>
          </span>
        }
      >
        <p className="muted">
          {engineSourceText(data)}. New runs and Style studio rewrites in this workspace use this engine; each brief's
          spending limit still applies, and every artifact records the provider and model that wrote it.
        </p>
        {data.problem && (
          <div className="banner banner-warning" role="status">
            {data.problem}
          </div>
        )}
        <form className="stack" onSubmit={submit}>
          <fieldset className="pill-group">
            <legend>Provider</legend>
            {data.providers.map((p) => (
              <label key={p.id} className={provider === p.id ? "pill selected" : "pill"}>
                <input
                  type="radio"
                  name={`${ids}-provider`}
                  value={p.id}
                  checked={provider === p.id}
                  onChange={() => choose(p.id)}
                />
                {p.label}
                {p.id === "gemini" && <span className="small muted"> (recommended)</span>}
              </label>
            ))}
          </fieldset>
          <div className="grid-2">
            <div className="stack">
              <label className="field">
                <span>Model</span>
                <select value={model} onChange={(e) => pickModel(e.target.value)}>
                  {models.map((m) => {
                    const d = details.find((x) => x.id === m);
                    const tier = d?.free_tier === true ? " (free tier)" : d?.free_tier === false ? " (paid tier only)" : "";
                    return (
                      <option key={m} value={m}>
                        {d ? `${d.label}: ${m}${tier}` : m}
                      </option>
                    );
                  })}
                </select>
              </label>
              {levels.length > 0 && (
                <label className="field">
                  <span>Thinking depth (planner, writer, reviewer, Style studio)</span>
                  <select value={thinking} onChange={(e) => setThinking(e.target.value as ThinkingLevel | "")}>
                    <option value="">Model default</option>
                    {levels.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {provider === "gemini" && (
                <p className="small muted">
                  If this model is unavailable for the key or out of quota, the next of Gemini 4 Hydrogen, 3.1 Pro, 3.8
                  Flash and 3.5 Flash-Lite answers. Researchers use Gemini 4 Hydrogen at medium thinking.
                </p>
              )}
            </div>
            <div className="field">
              <label htmlFor={`${ids}-key`}>API key</label>
              <div className="row">
                <input
                  id={`${ids}-key`}
                  type={showKey ? "text" : "password"}
                  autoComplete="off"
                  spellCheck={false}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={keepsKey ? `Saved key ending ${data.key_hint}: leave empty to keep it` : KEY_HINTS[provider]}
                  aria-describedby={`${ids}-key-help`}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  aria-pressed={showKey}
                  onClick={() => setShowKey((v) => !v)}
                >
                  {showKey ? "Hide" : "Show"}
                </button>
              </div>
              <span id={`${ids}-key-help`} className="small muted">
                Encrypted on the server and never shown again. Use a key with its own spending limit.
              </span>
            </div>
          </div>
          {save.isError && <ErrorBanner error={save.error} title="The engine was not saved" />}
          <div className="row wrap">
            <button type="submit" className="btn btn-primary" disabled={save.isPending || (!apiKey.trim() && !keepsKey)}>
              {save.isPending ? "Saving…" : "Save and use this engine"}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={runTest}
              disabled={test.isPending || (!apiKey.trim() && !data.live)}
            >
              {test.isPending ? "Testing…" : "Test connection"}
            </button>
            {data.source === "workspace" && (
              <ConfirmButton
                label="Remove workspace key"
                prompt="Remove this workspace's key? Runs fall back to the deployment's engine."
                confirmLabel="Yes, remove"
                pending={remove.isPending}
                className="btn btn-ghost"
                onConfirm={() => remove.mutate()}
              />
            )}
          </div>
          {test.data && (
            <p className={test.data.ok ? "text-success" : "text-warning"} role="status" data-testid="engine-test">
              {test.data.ok
                ? `✓ Connected to ${test.data.model} · ${test.data.latency_ms} ms`
                : `✗ ${test.data.detail} (${test.data.latency_ms} ms)`}
            </p>
          )}
        </form>
      </Card>
    </div>
  );
}
