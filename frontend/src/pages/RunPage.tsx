import { useEffect, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import {
  isTerminal,
  useDecide,
  useEvidence,
  useExportReport,
  useReportVersion,
  useReviews,
  useRun,
  useRunAction,
  useRunEvents,
  useSources,
  useUsage,
} from "../api/hooks";
import type {
  Evidence,
  Generation,
  Me,
  PlanBody,
  ReportBody,
  ReviewFinding,
  ReviewRound,
  RunDetail,
  RunEvent,
  Severity,
} from "../api/types";
import { PlanEditor } from "../components/PlanEditor";
import { Badge, Card, EmptyState, ErrorBanner, Spinner, StateBadge } from "../components/ui";
import {
  CLAIM_KIND_LABELS,
  CLAIM_KIND_TONES,
  describeEvent,
  formatDateTime,
  formatTime,
  REVIEW_OUTCOMES,
  SEVERITY_TONES,
} from "../format";

type Tab = "report" | "plan" | "evidence";

export function RunPage() {
  const { runId = "" } = useParams();
  const me = useOutletContext<Me>();
  const run = useRun(runId);
  const [epoch, setEpoch] = useState(0);
  const stream = useRunEvents(runId, epoch);
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
        <div className="row wrap end">
          <RunActions run={detail} role={role} onRetried={() => setEpoch((e) => e + 1)} />
          <StateBadge state={detail.state} />
        </div>
      </div>

      {detail.state === "CANCEL_REQUESTED" && (
        <div className="banner banner-warning" role="status">
          <strong>Stopping.</strong> No new steps, tool calls or model calls will start; calls already in flight
          finish and are recorded.
        </div>
      )}
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
          {activeTab === "plan" && <PlanView run={detail} role={role} />}
          {activeTab === "report" && <ReportView run={detail} />}
          {activeTab === "evidence" && <EvidenceList runId={detail.id} />}
        </div>
        <div className="stack side">
          <CostCard runId={detail.id} />
          <Timeline events={stream.events} status={stream.status} terminal={isTerminal(detail.state)} />
        </div>
      </div>
    </div>
  );
}

function RunActions({ run, role, onRetried }: { run: RunDetail; role: string | undefined; onRetried: () => void }) {
  const cancel = useRunAction(run.id, "cancel");
  const retry = useRunAction(run.id, "retry");
  const [confirming, setConfirming] = useState(false);
  const canAct = role === "analyst" || role === "admin";
  if (!canAct) return null;
  const cancellable = !isTerminal(run.state) && run.state !== "CANCEL_REQUESTED";
  const error = cancel.error ?? retry.error;

  return (
    <div className="run-actions row wrap">
      {cancellable && !confirming && (
        <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
          Cancel run
        </button>
      )}
      {cancellable && confirming && (
        <div className="row wrap" role="group" aria-label="Confirm cancellation">
          <span className="small">Stop this run? This cannot be undone.</span>
          <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)}>
            Keep running
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate(undefined, { onSettled: () => setConfirming(false) })}
          >
            Yes, cancel run
          </button>
        </div>
      )}
      {run.state === "FAILED" && (
        <button
          type="button"
          className="btn btn-primary"
          disabled={retry.isPending}
          onClick={() => retry.mutate(undefined, { onSuccess: onRetried })}
        >
          Retry from last checkpoint
        </button>
      )}
      {error && <ErrorBanner error={error} title="Action failed" />}
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

function GenerationNote({ artifact }: { artifact: { author?: string; generation?: Generation | null } }) {
  const g = artifact.generation;
  if (artifact.author === "user") {
    return <p className="small muted">Edited by a person{g?.edited_from ? ` from v${g.edited_from}` : ""}.</p>;
  }
  if (!g || g.provider === "fake") return <p className="small muted">Produced by the deterministic test agent.</p>;
  return (
    <p className="small muted" data-testid="generation">
      Produced by {g.model} via {g.provider} · prompt {g.prompt_version} · {g.attempts} attempt(s) ·{" "}
      {(g.input_tokens ?? 0) + (g.output_tokens ?? 0)} tokens
    </p>
  );
}

function PlanView({ run, role }: { run: RunDetail; role: string | undefined }) {
  const [editing, setEditing] = useState(false);
  if (!run.plan) {
    return <Card><EmptyState title="No plan yet"><p className="muted">The planner is working on it.</p></EmptyState></Card>;
  }
  const canEdit = run.pending_decision?.kind === "plan" && (role === "analyst" || role === "admin");
  if (editing && canEdit) {
    return <PlanEditor runId={run.id} plan={run.plan} onDone={() => setEditing(false)} />;
  }
  const plan: PlanBody = run.plan.body;
  const levels = dependencyLevels(plan);
  return (
    <Card
      title={`Plan v${run.plan.version}`}
      actions={canEdit && <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>Edit plan</button>}
    >
      <GenerationNote artifact={run.plan} />
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
  const latest = run.report?.version ?? null;
  const [viewing, setViewing] = useState<number | null>(null);
  const shown = viewing ?? latest;
  const older = useReportVersion(run.id, shown !== null && shown !== latest ? shown : null);
  const evidence = useEvidence(run.id, Boolean(run.report));
  const reviews = useReviews(run.id, Boolean(run.report));
  const [selected, setSelected] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);

  useEffect(() => {
    if (focused) document.getElementById(`claim-${focused}`)?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [focused, shown]);

  if (!run.report || shown === null) {
    return <Card><EmptyState title="No report yet"><p className="muted">Drafting starts after research.</p></EmptyState></Card>;
  }
  const artifact = shown === latest ? run.report : older.data;
  if (!artifact) {
    return older.isError ? <ErrorBanner error={older.error} title="Could not load this version" /> : <Spinner label="Loading version…" />;
  }
  const report: ReportBody = artifact.body;
  const byId = new Map((evidence.data ?? []).map((e) => [e.evidence_id, e]));
  const passage = selected ? byId.get(selected) : undefined;
  const decision = run.decisions.find((d) => d.kind === "report" && d.version === shown);
  const round = reviews.data?.find((r) => r.report_version === shown);
  const flags = claimFlags(round?.findings ?? []);
  const showClaim = (version: number, claimId: string) => {
    setViewing(version === latest ? null : version);
    setFocused(claimId);
  };

  return (
    <div className="stack">
      <div className="report-layout">
        <Card
          title={`Report v${shown}`}
          actions={
            <div className="row wrap">
              {latest !== null && latest > 1 && (
                <div className="versions" role="group" aria-label="Report version">
                  {Array.from({ length: latest }, (_, i) => i + 1).map((v) => (
                    <button key={v} type="button" aria-pressed={v === shown} onClick={() => setViewing(v === latest ? null : v)}>
                      v{v}
                    </button>
                  ))}
                </div>
              )}
              {decision?.decision === "approve" ? (
                <Badge tone="success">Approved</Badge>
              ) : decision ? (
                <Badge tone="danger">Rejected</Badge>
              ) : shown !== latest ? (
                <Badge>Superseded</Badge>
              ) : (
                <Badge>Draft</Badge>
              )}
            </div>
          }
        >
          <GenerationNote artifact={artifact} />
          {shown !== latest && (
            <p className="banner small" role="status">
              Earlier version kept for audit. The reviewer flagged the highlighted claims; v{latest} is current.
            </p>
          )}
          {report.sections.map((section) => (
            <section key={section.section_id} className="report-section">
              <h3>{section.title}</h3>
              <ul className="claims">
                {section.claims.map((claim) => {
                  const flag = flags.get(claim.claim_id);
                  return (
                    <li
                      key={claim.claim_id}
                      id={`claim-${claim.claim_id}`}
                      className={`claim${flag ? ` flag-${flag}` : ""}${focused === claim.claim_id ? " focused" : ""}`}
                      data-flag={flag}
                    >
                      <Badge tone={CLAIM_KIND_TONES[claim.kind]}>{CLAIM_KIND_LABELS[claim.kind]}</Badge>
                      <span className="claim-text">{claim.text}</span>
                      {flag && <Badge tone={SEVERITY_TONES[flag]}>{`Reviewer: ${flag}`}</Badge>}
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
                  );
                })}
              </ul>
            </section>
          ))}
          <ExportControls runId={run.id} version={shown} approved={decision?.decision === "approve"} />
        </Card>
        {selected && (
          <aside className="card evidence-panel" aria-label="Cited evidence">
            {passage ? <EvidenceItem item={passage} /> : <Spinner label="Loading evidence…" />}
            <button type="button" className="btn btn-ghost" onClick={() => setSelected(null)}>Close</button>
          </aside>
        )}
      </div>
      <ReviewPanel rounds={reviews.data ?? []} shown={shown} onShowClaim={showClaim} />
    </div>
  );
}

const SEVERITY_ORDER: Severity[] = ["blocker", "major", "minor"];

function claimFlags(findings: ReviewFinding[]): Map<string, Severity> {
  const flags = new Map<string, Severity>();
  for (const finding of findings) {
    for (const id of finding.claim_ids) {
      const current = flags.get(id);
      if (!current || SEVERITY_ORDER.indexOf(finding.severity) < SEVERITY_ORDER.indexOf(current)) {
        flags.set(id, finding.severity);
      }
    }
  }
  return flags;
}

function ExportControls({ runId, version, approved }: { runId: string; version: number; approved: boolean }) {
  const exporter = useExportReport(runId);
  return (
    <div className="export-controls stack">
      <div className="row wrap">
        <button type="button" className="btn btn-secondary" disabled={exporter.isPending} onClick={() => exporter.mutate(version)}>
          {approved ? `Download approved report (v${version})` : `Download draft (v${version})`}
        </button>
        <span className="small muted">
          {approved
            ? "Markdown with approver, time, and digest."
            : "Markdown watermarked “DRAFT - NOT APPROVED” until a reviewer approves this version."}
        </span>
      </div>
      {exporter.isError && <ErrorBanner error={exporter.error} title="Export failed" />}
      {exporter.data && (
        <p className="small muted" role="status" data-testid="export-status">
          Saved {exporter.data.filename} ({exporter.data.kind}) · sha256{" "}
          <code title={exporter.data.sha256 ?? ""}>{(exporter.data.sha256 ?? "").slice(0, 12)}…</code>
        </p>
      )}
    </div>
  );
}

function ReviewPanel({
  rounds,
  shown,
  onShowClaim,
}: {
  rounds: ReviewRound[];
  shown: number;
  onShowClaim: (version: number, claimId: string) => void;
}) {
  if (!rounds.length) return null;
  return (
    <Card title="Review" className="review-card">
      <p className="small muted">
        Automatic checks verify that figures and wording appear in the cited passages; a model reviewer (when
        configured) checks meaning. Neither replaces your judgement: they only decide whether the writer revises.
      </p>
      <ol className="review-rounds">
        {rounds.map((round) => (
          <li key={round.report_version} className="review-round" aria-current={round.report_version === shown}>
            <header>
              <strong>Round {round.review_round}</strong>
              <span className="muted small">report v{round.report_version} · {formatDateTime(round.reviewed_at)}</span>
              <Badge tone={round.outcome === "pass" ? "success" : "warning"}>
                {REVIEW_OUTCOMES[round.outcome] ?? round.outcome}
              </Badge>
            </header>
            {round.findings.length === 0 ? (
              <p className="small muted">No findings.</p>
            ) : (
              <ul className="findings">
                {round.findings.map((finding) => (
                  <li key={finding.finding_id} className="finding" data-testid="finding">
                    <div className="row wrap small">
                      <Badge tone={SEVERITY_TONES[finding.severity]}>{finding.severity}</Badge>
                      <span>{finding.category.replaceAll("_", " ")}</span>
                      <span className="muted">
                        · {finding.source === "deterministic" ? "automatic check" : "model reviewer"}
                      </span>
                    </div>
                    <p>{finding.requested_action}</p>
                    {finding.claim_ids.length > 0 && (
                      <p className="small">
                        Claims:{" "}
                        {finding.claim_ids.map((id, i) => (
                          <span key={id}>
                            {i > 0 && ", "}
                            <button type="button" className="link-button" onClick={() => onShowClaim(round.report_version, id)}>
                              {id}
                            </button>
                          </span>
                        ))}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function EvidenceList({ runId }: { runId: string }) {
  const evidence = useEvidence(runId, true);
  const sources = useSources(runId, true);
  if (evidence.isPending) return <Spinner label="Loading evidence…" />;
  if (evidence.isError) return <ErrorBanner error={evidence.error} title="Could not load evidence" />;
  return (
    <div className="stack">
      {sources.data && sources.data.length > 0 && (
        <Card title={`Sources (${sources.data.length})`}>
          <ul className="sources">
            {sources.data.map((source) => (
              <li key={source.source_id} className="source-row">
                {source.fetch_status === "fetched" ? (
                  <Badge tone="success">{source.kind === "upload" ? "Document" : "Read"}</Badge>
                ) : (
                  <Badge tone="danger">Not read</Badge>
                )}
                <SourceLink url={source.url} title={source.title ?? source.source_id} />
                <span className="small muted">
                  {source.fetch_status === "failed"
                    ? ` · ${(source.failure_reason ?? "failed").replaceAll("_", " ")}; never cited`
                    : ` · ${source.passages} passage(s)`}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {!evidence.data.length ? (
        <Card><EmptyState title="No evidence yet"><p className="muted">Passages appear as research tasks complete.</p></EmptyState></Card>
      ) : (
        <Card title={`Evidence (${evidence.data.length} passages)`}>
          <ul className="evidence-list">
            {evidence.data.map((item) => (
              <li key={item.evidence_id}><EvidenceItem item={item} /></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
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
          {item.source_kind === "upload" ? " · uploaded document" : ""}
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

const money = (value: string | null | undefined) => `$${Number(value ?? 0).toFixed(4)}`;

function CostCard({ runId }: { runId: string }) {
  const usage = useUsage(runId);
  if (!usage.data) return null;
  const u = usage.data;
  const used = Number(u.committed);
  const budget = Number(u.budget);
  const percent = budget > 0 ? Math.min(100, (used / budget) * 100) : 0;
  return (
    <Card title="Cost (estimated)" className="cost-card">
      <div className="meter" role="meter" aria-label="Budget used" aria-valuemin={0} aria-valuemax={budget}
           aria-valuenow={used}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <p className="small">
        <strong>{money(u.committed)}</strong> of {money(u.budget)} committed · reconciled {money(u.reconciled)}
        {Number(u.outstanding) > 0 && <> · in flight {money(u.outstanding)}</>}
        {Number(u.uncertain) > 0 && <> · uncertain {money(u.uncertain)}</>}
      </p>
      {u.lines.length > 0 && (
        <table className="table compact">
          <thead>
            <tr><th scope="col">Step</th><th scope="col">Calls</th><th scope="col">Tokens</th><th scope="col">Actual</th></tr>
          </thead>
          <tbody>
            {u.lines.map((line) => (
              <tr key={`${line.step}-${line.kind}`}>
                <td>{line.step} <span className="muted small">{line.kind}</span></td>
                <td>{line.calls}</td>
                <td>{line.input_tokens + line.output_tokens || "-"}</td>
                <td>{line.actual === null ? "-" : money(line.actual)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="small muted">{u.note}</p>
    </Card>
  );
}
