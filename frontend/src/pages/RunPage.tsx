import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { isTerminal, useDecide, useEvidence, useRun, useRunEvents } from "../api/hooks";
import type { Evidence, Me, PlanBody, ReportBody, RunDetail, RunEvent } from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner, StateBadge } from "../components/ui";
import { CLAIM_KIND_LABELS, CLAIM_KIND_TONES, describeEvent, formatDateTime, formatTime } from "../format";

type Tab = "report" | "plan" | "evidence";

export function RunPage() {
  const { runId = "" } = useParams();
  const me = useOutletContext<Me>();
  const run = useRun(runId);
  const stream = useRunEvents(runId);
  const [tab, setTab] = useState<Tab | null>(null);

  if (run.isPending) return <Spinner label="Loading run…" />;
  if (run.isError) return <ErrorBanner error={run.error} title="Could not load this run" />;

  const detail = run.data;
  const role = me.memberships.find((m) => m.workspace_id === detail.workspace_id)?.role;
  const activeTab: Tab = tab ?? (detail.report ? "report" : "plan");

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/w/${detail.workspace_id}/runs`}>← All runs</Link>
          </p>
          <h1>{detail.topic}</h1>
          <p className="muted">
            For {detail.brief.audience} · started by {detail.created_by} on {formatDateTime(detail.created_at)}
          </p>
        </div>
        <StateBadge state={detail.state} />
      </div>

      {detail.outcome_reason && (detail.state === "FAILED" || detail.state === "NEEDS_ATTENTION") && (
        <div className={`banner ${detail.state === "FAILED" ? "banner-danger" : "banner-warning"}`} role="status">
          <strong>{detail.state === "FAILED" ? "Run failed." : "Needs attention."}</strong> {detail.outcome_reason}
        </div>
      )}

      <div className="run-layout">
        <div className="stack">
          <DecisionPanel run={detail} role={role} />
          <div className="tabs" role="tablist" aria-label="Run artifacts">
            {(["report", "plan", "evidence"] as Tab[]).map((name) => (
              <button
                key={name}
                role="tab"
                type="button"
                aria-selected={activeTab === name}
                className={activeTab === name ? "tab active" : "tab"}
                onClick={() => setTab(name)}
              >
                {name === "report" ? "Report" : name === "plan" ? "Plan" : "Evidence"}
                {name === "report" && detail.report && <span className="tab-meta">v{detail.report.version}</span>}
                {name === "plan" && detail.plan && <span className="tab-meta">v{detail.plan.version}</span>}
              </button>
            ))}
          </div>
          {activeTab === "plan" && <PlanView run={detail} />}
          {activeTab === "report" && <ReportView run={detail} />}
          {activeTab === "evidence" && <EvidenceList runId={detail.id} />}
        </div>
        <Timeline events={stream.events} status={stream.status} terminal={isTerminal(detail.state)} />
      </div>
    </div>
  );
}

function DecisionPanel({ run, role }: { run: RunDetail; role: string | undefined }) {
  const decide = useDecide(run.id);
  const [comment, setComment] = useState("");
  const pending = run.pending_decision;
  if (!pending) return null;

  const isPlan = pending.kind === "plan";
  const allowed = role === "admin" || (isPlan ? role === "analyst" : role === "reviewer");
  const noun = isPlan ? "plan" : "report";

  if (!allowed) {
    return (
      <div className="banner banner-waiting" role="status">
        Waiting for {isPlan ? "an analyst" : "a reviewer"} to approve {noun} v{pending.version}.
      </div>
    );
  }

  const submit = (decision: "approve" | "reject") =>
    decide.mutate({ kind: pending.kind, version: pending.version, digest: pending.digest, decision,
                    comment: comment.trim() || undefined });

  return (
    <Card className="decision" title={`Your decision: ${noun} v${pending.version}`}>
      <p className="muted">
        {isPlan
          ? "Research starts only after you approve this exact plan version. Rejecting asks the planner for a revision."
          : "Approving makes this exact report version exportable. Rejecting ends the run as needing attention."}
      </p>
      <p className="small muted">
        Binds to digest <code title={pending.digest}>{pending.digest.slice(0, 12)}…</code>
      </p>
      <label className="field">
        <span>Comment (optional{isPlan ? "; guides the revision if you reject" : ""})</span>
        <textarea rows={2} maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>
      {decide.isError && <ErrorBanner error={decide.error} title="Decision not recorded" />}
      <div className="row end">
        <button type="button" className="btn btn-secondary" disabled={decide.isPending} onClick={() => submit("reject")}>
          Reject {noun}
        </button>
        <button type="button" className="btn btn-primary" disabled={decide.isPending} onClick={() => submit("approve")}>
          Approve {noun} v{pending.version}
        </button>
      </div>
    </Card>
  );
}

function PlanView({ run }: { run: RunDetail }) {
  if (!run.plan) {
    return <Card><EmptyState title="No plan yet"><p className="muted">The planner is working on it.</p></EmptyState></Card>;
  }
  const plan: PlanBody = run.plan.body;
  const levels = dependencyLevels(plan);
  return (
    <Card title={`Plan v${run.plan.version}`}>
      <p>{plan.source_strategy}</p>
      <h3>Tasks</h3>
      <ol className="levels">
        {levels.map((level, index) => (
          <li key={index}>
            <span className="small muted">{index === 0 ? "Start" : `After step ${index}`}, in parallel</span>
            <ul className="tasks">
              {level.map((task) => (
                <li key={task.task_id} className="task">
                  <code>{task.task_id}</code> {task.question}
                  <div className="row wrap small">
                    {task.tools.map((tool) => <Badge key={tool}>{tool}</Badge>)}
                    {task.depends_on.length > 0 && <span className="muted">needs {task.depends_on.join(", ")}</span>}
                  </div>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      <h3>Report outline</h3>
      <ul>
        {plan.outline.map((section) => (
          <li key={section.section_id}>
            <strong>{section.title}</strong> <span className="muted">{section.purpose}</span>
          </li>
        ))}
      </ul>
      {plan.assumptions.length > 0 && (
        <>
          <h3>Assumptions</h3>
          <ul>{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </>
      )}
    </Card>
  );
}

function dependencyLevels(plan: PlanBody) {
  const done = new Set<string>();
  const remaining = [...plan.tasks];
  const levels: PlanBody["tasks"][] = [];
  while (remaining.length) {
    const ready = remaining.filter((t) => t.depends_on.every((d) => done.has(d)));
    if (!ready.length) break;
    levels.push(ready);
    ready.forEach((t) => {
      done.add(t.task_id);
      remaining.splice(remaining.indexOf(t), 1);
    });
  }
  return levels;
}

function ReportView({ run }: { run: RunDetail }) {
  const evidence = useEvidence(run.id, Boolean(run.report));
  const [selected, setSelected] = useState<string | null>(null);
  if (!run.report) {
    return <Card><EmptyState title="No report yet"><p className="muted">Drafting starts after research.</p></EmptyState></Card>;
  }
  const report: ReportBody = run.report.body;
  const byId = new Map((evidence.data ?? []).map((e) => [e.evidence_id, e]));
  const passage = selected ? byId.get(selected) : undefined;
  const approved = run.decisions.some((d) => d.kind === "report" && d.version === run.report?.version && d.decision === "approve");

  return (
    <div className="report-layout">
      <Card title={`Report v${run.report.version}`} actions={approved ? <Badge tone="success">Approved</Badge> : <Badge>Draft</Badge>}>
        {report.sections.map((section) => (
          <section key={section.section_id} className="report-section">
            <h3>{section.title}</h3>
            <ul className="claims">
              {section.claims.map((claim) => (
                <li key={claim.claim_id} className="claim">
                  <Badge tone={CLAIM_KIND_TONES[claim.kind]}>{CLAIM_KIND_LABELS[claim.kind]}</Badge>
                  <span className="claim-text">{claim.text}</span>
                  {claim.evidence_ids.map((id, i) => (
                    <button
                      key={id}
                      type="button"
                      className={`cite ${selected === id ? "active" : ""}`}
                      aria-label={`Show evidence ${id}`}
                      onClick={() => setSelected(selected === id ? null : id)}
                    >
                      [{i + 1}]
                    </button>
                  ))}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </Card>
      {selected && (
        <aside className="card evidence-panel" aria-label="Cited evidence">
          {passage ? <EvidenceItem item={passage} /> : <Spinner label="Loading evidence…" />}
          <button type="button" className="btn btn-ghost" onClick={() => setSelected(null)}>Close</button>
        </aside>
      )}
    </div>
  );
}

function EvidenceList({ runId }: { runId: string }) {
  const evidence = useEvidence(runId, true);
  if (evidence.isPending) return <Spinner label="Loading evidence…" />;
  if (evidence.isError) return <ErrorBanner error={evidence.error} title="Could not load evidence" />;
  if (!evidence.data.length) {
    return <Card><EmptyState title="No evidence yet"><p className="muted">Passages appear as research tasks complete.</p></EmptyState></Card>;
  }
  return (
    <Card title={`Evidence (${evidence.data.length} passages)`}>
      <ul className="evidence-list">
        {evidence.data.map((item) => (
          <li key={item.evidence_id}><EvidenceItem item={item} /></li>
        ))}
      </ul>
    </Card>
  );
}

function SourceLink({ url, title }: { url: string | null; title: string }) {
  const safe = url && /^https?:\/\//i.test(url);
  return safe ? (
    <a href={url} target="_blank" rel="noopener noreferrer nofollow">{title}</a>
  ) : (
    <span>{title}</span>
  );
}

function EvidenceItem({ item }: { item: Evidence }) {
  return (
    <article className="evidence">
      <header className="small">
        <SourceLink url={item.source_url} title={item.source_title ?? item.source_id} />
        <span className="muted">
          {" · "}task {item.task_id}
          {item.locator ? ` · ${item.locator}` : ""}
          {" · retrieved "}
          {formatDateTime(item.retrieved_at)}
          {item.published_on ? ` · published ${item.published_on}` : " · publication date unknown"}
        </span>
      </header>
      <blockquote>{item.text}</blockquote>
      <p className="small muted">
        <code>{item.evidence_id}</code> · sha256 <code title={item.text_sha256}>{item.text_sha256.slice(0, 12)}…</code>
      </p>
    </article>
  );
}

function Timeline({ events, status, terminal }: { events: RunEvent[]; status: string; terminal: boolean }) {
  return (
    <Card
      className="timeline-card"
      title="Timeline"
      actions={
        <span className="small muted" data-testid="stream-status">
          <span className={`dot dot-${status === "live" ? "ok" : status === "ended" ? "idle" : "checking"}`} aria-hidden="true" />
          {status === "live" ? "Live" : status === "ended" ? (terminal ? "Finished" : "Disconnected") : "Connecting…"}
        </span>
      }
    >
      {events.length === 0 ? (
        <p className="muted">No events yet.</p>
      ) : (
        <ol className="timeline" aria-live="polite">
          {events.map((event) => (
            <li key={event.id} className={`event event-${event.type}`}>
              <time dateTime={event.created_at}>{formatTime(event.created_at)}</time>
              <span>{describeEvent(event)}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
