/** The real workflow of every run (backend/app/workflow), as a flow of agents and the two
 *  human approval gates. Used on the sign-in page (overview) and the Agents page (interactive). */

export type FlowStep = {
  id: string;
  name: string;
  kind: "agent" | "human";
  short: string;
  does: string;
  input: string;
  output: string;
  tools: string[];
  guards: string[];
  prompt?: string;
};

export const FLOW: FlowStep[] = [
  {
    id: "planner",
    name: "Planner",
    kind: "agent",
    short: "Brief to typed plan",
    does: "Turns the brief into a typed research plan: tasks, their dependencies, tools and the report outline.",
    input: "The brief: topic, audience, research questions, source policy and limits.",
    output: "A versioned plan that a person approves, edits or rejects.",
    tools: ["None: planning only"],
    guards: ["JSON-schema contract for the plan", "Human approval of the exact plan version before any research"],
    prompt: "planner/v1",
  },
  {
    id: "plan-gate",
    name: "Plan approval",
    kind: "human",
    short: "A person approves",
    does: "An analyst or admin approves, edits or rejects the exact plan version. Nothing is researched before this.",
    input: "Plan version n and its digest.",
    output: "An approval bound to that version; an edit creates version n+1 that needs its own approval.",
    tools: [],
    guards: ["Approving v2 never approves an edited v3", "Recorded in the activity log"],
  },
  {
    id: "researchers",
    name: "Researchers ×N",
    kind: "agent",
    short: "Parallel evidence",
    does: "Each runs one plan task: searches, fetches pages or workspace documents, and extracts passages with provenance.",
    input: "One task with its questions and the brief's source policy.",
    output: "Evidence passages with source, retrieval date and hash.",
    tools: ["Web search (Tavily) or the offline corpus", "Uploaded documents", "SSRF-safe page fetcher"],
    guards: [
      "Run in parallel, bounded by the brief's limits",
      "Domain allow and block lists",
      "Budget reserved before every model or search call",
    ],
    prompt: "researcher/v1",
  },
  {
    id: "writer",
    name: "Writer",
    kind: "agent",
    short: "Cited draft",
    does: "Drafts the report from the collected evidence only; every claim is labelled and cited.",
    input: "The approved plan and this run's evidence.",
    output: "A report version whose citations point at this run's passages.",
    tools: ["This run's evidence only"],
    guards: ["Citations validated against this run's evidence", "Revises the draft when the reviewer finds blockers"],
    prompt: "writer/v1",
  },
  {
    id: "reviewer",
    name: "Reviewer",
    kind: "agent",
    short: "Checks every claim",
    does: "Checks claims against their cited passages and flags unsupported figures, gaps and conflicts.",
    input: "The draft and the passages it cites.",
    output: "Findings by severity; blockers send the draft back to the writer (at most 2 rounds).",
    tools: ["Deterministic support checks", "The model, when configured"],
    guards: ["At most 2 review rounds, then the run needs attention"],
    prompt: "reviewer/v1",
  },
  {
    id: "report-gate",
    name: "Report approval",
    kind: "human",
    short: "A reviewer signs off",
    does: "A reviewer approves the exact final report version; only then can it be exported as approved.",
    input: "Report version n, its findings and evidence.",
    output: "An approved export that records who approved which version, with its digest.",
    tools: [],
    guards: ["Bound to the report version and digest", "Recorded in the activity log"],
  },
];

export function AgentFlow({
  selected,
  onSelect,
  label = "Workflow of every run",
}: {
  selected?: string;
  onSelect?: (id: string) => void;
  label?: string;
}) {
  return (
    <ol className={`flow ${onSelect ? "flow-interactive" : ""}`} aria-label={label}>
      {FLOW.map((step, index) => {
        const body = (
          <>
            <span className="flow-index" aria-hidden="true">
              {step.kind === "human" ? "✓" : index + 1}
            </span>
            <span className="flow-text">
              <span className="flow-name">{step.name}</span>
              <span className="flow-short">{step.short}</span>
            </span>
          </>
        );
        return (
          <li key={step.id} className={`flow-step flow-${step.kind}${step.id === "reviewer" ? " flow-loop" : ""}`}>
            {onSelect ? (
              <button
                type="button"
                className="flow-node"
                aria-pressed={selected === step.id}
                onClick={() => onSelect(step.id)}
              >
                {body}
              </button>
            ) : (
              <span className="flow-node">{body}</span>
            )}
            {index < FLOW.length - 1 && <span className="flow-edge" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}
