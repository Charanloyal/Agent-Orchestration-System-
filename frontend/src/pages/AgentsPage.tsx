import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { useAiEngine, useDocumentTitle, useTestAiEngine } from "../api/hooks";
import type { Me } from "../api/types";
import { AgentFlow, FLOW } from "../components/AgentFlow";
import { engineSourceText } from "../components/AiEngineCard";
import { Card } from "../components/ui";

const SEARCH_LABELS: Record<string, string> = {
  fake: "Deterministic demo sources",
  tavily: "Tavily web search",
  corpus: "Offline evaluation corpus",
};

/** The agents and approval gates behind every run, so users and examiners can see what each
 *  does and which rules constrain it. Describes the real workflow; nothing here changes how
 *  runs execute. */
export function AgentsPage() {
  useDocumentTitle("Agents");
  const me = useOutletContext<Me>();
  const { workspaceId = "" } = useParams();
  const engine = useAiEngine(workspaceId).data;
  const live = engine ? engine.live : me.deployment?.agent_mode === "llm";
  const [selected, setSelected] = useState("planner");
  const step = FLOW.find((s) => s.id === selected) ?? FLOW[0];
  const agents = FLOW.filter((s) => s.kind === "agent").length;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Agents</h1>
          <p className="muted">
            {agents} agents and two human approval gates turn a brief into an approved, cited report. Select a step
            to see what it does and what constrains it.
          </p>
        </div>
        <span className={`badge ${live ? "badge-success" : "badge-waiting"}`} data-testid="agent-mode">
          {live ? "Language-model agents" : "Deterministic demo agents"}
        </span>
      </div>
      {!live && (
        <p className="small muted">
          This deployment runs deterministic demo agents: the workflow, approvals, citations and recovery are real,
          but the text is not written by a language model.
        </p>
      )}

      <Card title="Workflow" className="flow-card">
        <AgentFlow selected={selected} onSelect={setSelected} />
        <p className="small muted flow-note">
          The reviewer can send a draft back to the writer at most twice. A run waiting for a person holds no worker.
        </p>
      </Card>

      {step && (
        <div className="bento">
          <section className="card flow-drawer span-8" aria-labelledby="step-title" aria-live="polite">
            <header className="card-header">
              <h2 id="step-title">{step.name}</h2>
              <span className={`badge ${step.kind === "human" ? "badge-waiting" : "badge-progress"}`}>
                {step.kind === "human" ? "Human approval" : "Agent"}
              </span>
            </header>
            <p>{step.does}</p>
            <dl className="agent-io">
              <dt>Input</dt>
              <dd>{step.input}</dd>
              <dt>Output</dt>
              <dd>{step.output}</dd>
              {step.tools.length > 0 && (
                <>
                  <dt>Tools</dt>
                  <dd>{step.tools.join(" · ")}</dd>
                </>
              )}
              {step.prompt && (
                <>
                  <dt>Prompt</dt>
                  <dd>
                    <code>{step.prompt}</code> (recorded with every artifact it produces)
                  </dd>
                </>
              )}
            </dl>
            <h3>Guards</h3>
            <ul className="agent-guards">
              {step.guards.map((guard) => (
                <li key={guard}>{guard}</li>
              ))}
            </ul>
          </section>
          <EngineCard workspaceId={workspaceId} me={me} />
        </div>
      )}
    </div>
  );
}

/** The engine this workspace's agents use, and a live diagnostic for admins. */
function EngineCard({ workspaceId, me }: { workspaceId: string; me: Me }) {
  const engine = useAiEngine(workspaceId);
  const test = useTestAiEngine(workspaceId);
  const isAdmin = me.memberships.find((m) => m.workspace_id === workspaceId)?.role === "admin";
  const data = engine.data;
  return (
    <Card title="This workspace's engine" className="span-4">
      <dl className="agent-io">
        <dt>Engine</dt>
        <dd data-testid="engine-label">
          {data?.live ? `${data.label} (live language model)` : "Deterministic demo agents"}
        </dd>
        <dt>Source</dt>
        <dd>{data ? engineSourceText(data) : "…"}</dd>
        <dt>Search</dt>
        <dd>{SEARCH_LABELS[me.deployment?.search_provider ?? "fake"] ?? me.deployment?.search_provider}</dd>
        <dt>Budget</dt>
        <dd>Each brief sets a spending limit; every model or search call reserves its cost first.</dd>
        <dt>Also used by</dt>
        <dd>
          The <Link to={`/w/${workspaceId}/style`}>Style studio</Link> rewrites with this engine, checked by its fact
          lock.
        </dd>
      </dl>
      {isAdmin && (
        <div className="row wrap">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={!data?.live || test.isPending}
            onClick={() => test.mutate({})}
          >
            {test.isPending ? "Testing…" : "Run engine diagnostic"}
          </button>
          <Link to={`/w/${workspaceId}/settings#ai-engine`}>Engine settings</Link>
        </div>
      )}
      {test.data && (
        <p className={test.data.ok ? "small text-success" : "small text-warning"} role="status">
          {test.data.ok
            ? `✓ ${test.data.model} answered in ${test.data.latency_ms} ms`
            : `✗ ${test.data.detail} (${test.data.latency_ms} ms)`}
        </p>
      )}
      <p className="small muted">
        Per-run calls, tokens and costs are on each run's cost card and on the{" "}
        <Link to={`/w/${workspaceId}/usage`}>usage page</Link>.
      </p>
    </Card>
  );
}
