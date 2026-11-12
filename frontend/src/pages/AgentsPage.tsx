import { useOutletContext } from "react-router";

import { useDocumentTitle } from "../api/hooks";
import type { Me } from "../api/types";
import { Card } from "../components/ui";

type Agent = { name: string; does: string; input: string; output: string; guards: string[] };

// The four agents of the workflow (backend/app/agents), in the order a run uses them.
const AGENTS: Agent[] = [
  {
    name: "Planner",
    does: "Turns the brief into a typed research plan: tasks, their dependencies, tools and the report outline.",
    input: "The brief: topic, audience, research questions, source policy and limits.",
    output: "A versioned plan that a person approves, edits or rejects.",
    guards: ["JSON-schema contract for the plan", "Human approval of the exact plan version before any research"],
  },
  {
    name: "Researcher",
    does: "Runs one plan task: searches, fetches pages or workspace documents, and extracts passages with provenance.",
    input: "One task with its questions and the brief's source policy.",
    output: "Evidence passages with source, retrieval date and hash.",
    guards: [
      "Several researchers run in parallel, bounded by the brief's limits",
      "SSRF-safe fetcher and domain allow/block lists",
      "Budget reserved before every model or search call",
    ],
  },
  {
    name: "Writer",
    does: "Drafts the report from the collected evidence only; every claim is labelled and cited.",
    input: "The approved plan and this run's evidence.",
    output: "A report version whose citations point at this run's passages.",
    guards: ["Citations validated against this run's evidence", "Revises the draft when the reviewer finds blockers"],
  },
  {
    name: "Reviewer",
    does: "Checks claims against their cited passages and flags unsupported figures, gaps and conflicts.",
    input: "The draft and the passages it cites.",
    output: "Findings by severity; blockers send the draft back to the writer.",
    guards: [
      "Deterministic support checks plus the model",
      "at most 2 review rounds, then the run needs attention",
      "Human approval of the exact final report version before an approved export",
    ],
  },
];

/** The agents behind every run, so users and examiners can see what each one does and which
 *  rules constrain it. Describes the real workflow; nothing here changes how runs execute. */
export function AgentsPage() {
  useDocumentTitle("Agents");
  const me = useOutletContext<Me>();
  const live = me.deployment?.agent_mode === "llm";

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Agents</h1>
          <p className="muted">The four agents that turn a brief into an approved, cited report.</p>
        </div>
        <span className={`badge ${live ? "badge-success" : "badge-waiting"}`} data-testid="agent-mode">
          {live ? "Language-model agents" : "Deterministic demo agents"}
        </span>
      </div>
      {!live && (
        <p className="small muted">
          This deployment runs deterministic demo agents: the workflow, approvals, citations and
          recovery are real, but the text is not written by a language model.
        </p>
      )}
      <ol className="agent-list" aria-label="Agents in pipeline order">
        {AGENTS.map((agent, index) => (
          <li key={agent.name}>
            <Card>
              <div className="agent-head">
                <span className="agent-step" aria-hidden="true">{index + 1}</span>
                <h2>{agent.name}</h2>
              </div>
              <p>{agent.does}</p>
              <dl className="agent-io">
                <dt>Input</dt>
                <dd>{agent.input}</dd>
                <dt>Output</dt>
                <dd>{agent.output}</dd>
              </dl>
              <ul className="agent-guards">
                {agent.guards.map((guard) => (
                  <li key={guard}>{guard}</li>
                ))}
              </ul>
            </Card>
          </li>
        ))}
      </ol>
    </div>
  );
}
