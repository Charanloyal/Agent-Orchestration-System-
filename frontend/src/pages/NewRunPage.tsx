import { useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { ApiError, newIdempotencyKey } from "../api/client";
import { useCreateRun } from "../api/hooks";
import type { BriefInput, SourceType } from "../api/types";
import { Card, ErrorBanner } from "../components/ui";

const SOURCE_TYPES: { value: SourceType; label: string }[] = [
  { value: "public_web", label: "Public web" },
  { value: "vendor_docs", label: "Vendor documentation" },
  { value: "uploaded_documents", label: "Uploaded documents" },
];

const splitList = (value: string): string[] =>
  value
    .split(/[\n,]/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);

export function NewRunPage() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const createRun = useCreateRun(workspaceId);
  // One key per form instance: double submits and retries can never create two runs.
  const idempotencyKey = useMemo(() => newIdempotencyKey(), []);

  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [sourceTypes, setSourceTypes] = useState<SourceType[]>(["public_web", "vendor_docs"]);
  const [allowedDomains, setAllowedDomains] = useState("");
  const [blockedDomains, setBlockedDomains] = useState("");
  const [dateCutoff, setDateCutoff] = useState("");
  const [budget, setBudget] = useState("2.00");
  const [maxTasks, setMaxTasks] = useState(6);
  const [deadline, setDeadline] = useState(60);

  const filledQuestions = questions.map((q) => q.trim()).filter(Boolean);
  const canSubmit = topic.trim().length >= 5 && audience.trim() && filledQuestions.length > 0 && sourceTypes.length > 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    const brief: BriefInput = {
      topic: topic.trim(),
      audience: audience.trim(),
      research_questions: filledQuestions,
      source_policy: {
        allowed_source_types: sourceTypes,
        allowed_domains: splitList(allowedDomains),
        blocked_domains: splitList(blockedDomains),
        date_cutoff: dateCutoff || null,
      },
      output_format: "markdown",
      budget: { currency: "USD", max_estimated_cost: Number(budget).toFixed(2) },
      limits: {
        max_tasks: maxTasks,
        max_parallel_tasks: 2,
        max_tool_calls: 60,
        max_review_rounds: 2,
        deadline_minutes: deadline,
      },
    };
    createRun.mutate({ brief, idempotencyKey }, { onSuccess: (run) => navigate(`/runs/${run.id}`) });
  }

  const validation =
    createRun.error instanceof ApiError && createRun.error.status === 422
      ? (createRun.error.details as { loc: (string | number)[]; msg: string }[] | undefined)
      : undefined;

  return (
    <form className="stack narrow" onSubmit={submit} noValidate>
      <div className="page-header">
        <div>
          <h1>New research brief</h1>
          <p className="muted">The planner proposes a plan from this brief. Nothing is researched until you approve it.</p>
        </div>
      </div>

      <Card title="What should be researched?">
        <label className="field">
          <span>Topic</span>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={300} required
                 placeholder="Compare self-hosted document search options for a 20-person team" />
        </label>
        <label className="field">
          <span>Intended audience</span>
          <input value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={500} required
                 placeholder="Engineering manager choosing a tool" />
        </label>
        <fieldset className="field">
          <legend>Research questions</legend>
          {questions.map((question, index) => (
            <div className="row" key={index}>
              <input
                aria-label={`Research question ${index + 1}`}
                value={question}
                maxLength={500}
                onChange={(e) => setQuestions(questions.map((q, i) => (i === index ? e.target.value : q)))}
                placeholder="Which options document SSO support?"
              />
              {questions.length > 1 && (
                <button type="button" className="btn btn-ghost" aria-label={`Remove question ${index + 1}`}
                        onClick={() => setQuestions(questions.filter((_, i) => i !== index))}>
                  Remove
                </button>
              )}
            </div>
          ))}
          {questions.length < 10 && (
            <button type="button" className="btn btn-secondary" onClick={() => setQuestions([...questions, ""])}>
              Add question
            </button>
          )}
        </fieldset>
      </Card>

      <Card title="Source policy">
        <fieldset className="field">
          <legend>Allowed source types</legend>
          <div className="row wrap">
            {SOURCE_TYPES.map((type) => (
              <label key={type.value} className="check">
                <input
                  type="checkbox"
                  checked={sourceTypes.includes(type.value)}
                  onChange={(e) =>
                    setSourceTypes(e.target.checked ? [...sourceTypes, type.value] : sourceTypes.filter((t) => t !== type.value))
                  }
                />
                {type.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid-2">
          <label className="field">
            <span>Only these domains (optional)</span>
            <textarea rows={2} value={allowedDomains} onChange={(e) => setAllowedDomains(e.target.value)}
                      placeholder="postgresql.org, docs.example.com" />
          </label>
          <label className="field">
            <span>Never these domains (optional)</span>
            <textarea rows={2} value={blockedDomains} onChange={(e) => setBlockedDomains(e.target.value)} />
          </label>
        </div>
        <label className="field narrow-field">
          <span>Ignore sources published before (optional)</span>
          <input type="date" value={dateCutoff} onChange={(e) => setDateCutoff(e.target.value)} />
        </label>
      </Card>

      <Card title="Limits">
        <div className="grid-3">
          <label className="field">
            <span>Budget ceiling (USD, estimated)</span>
            <input type="number" min="0.01" max="50" step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} />
          </label>
          <label className="field">
            <span>Maximum tasks</span>
            <input type="number" min={1} max={12} value={maxTasks} onChange={(e) => setMaxTasks(Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Deadline (minutes)</span>
            <input type="number" min={5} max={720} value={deadline} onChange={(e) => setDeadline(Number(e.target.value))} />
          </label>
        </div>
        <p className="small muted">
          Spend is reserved from estimates before provider calls; it is not a provider billing cap.
        </p>
      </Card>

      {createRun.isError && (
        <ErrorBanner error={createRun.error} title="The brief was not accepted" />
      )}
      {validation && (
        <ul className="validation" aria-label="Validation errors">
          {validation.map((item, i) => (
            <li key={i}>
              <code>{item.loc.slice(2).join(".") || "brief"}</code>: {item.msg}
            </li>
          ))}
        </ul>
      )}

      <div className="row end">
        <button type="submit" className="btn btn-primary" disabled={!canSubmit || createRun.isPending}>
          {createRun.isPending ? "Submitting…" : "Submit brief"}
        </button>
      </div>
    </form>
  );
}
