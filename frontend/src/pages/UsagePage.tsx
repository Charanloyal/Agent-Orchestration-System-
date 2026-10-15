import { useState } from "react";
import { Link, useParams } from "react-router";

import { useWorkspaceUsage } from "../api/hooks";
import { Card, EmptyState, ErrorBanner, Spinner, StateBadge } from "../components/ui";
import { formatDateTime } from "../format";

const money = (value: string | number) => `$${Number(value).toFixed(4)}`;
const PERIODS = [7, 30, 90] as const;

/** Estimated spend for the workspace (FR-09). Figures come from the configured price schedule
 *  and provider-reported usage, not from an invoice. */
export function UsagePage() {
  const { workspaceId = "" } = useParams();
  const [days, setDays] = useState<number>(30);
  const usage = useWorkspaceUsage(workspaceId, days);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Usage</h1>
          <p className="muted">Estimated model and search spend in this workspace.</p>
        </div>
        <div className="versions" role="group" aria-label="Period">
          {PERIODS.map((d) => (
            <button key={d} type="button" aria-pressed={d === days} onClick={() => setDays(d)}>
              {d} days
            </button>
          ))}
        </div>
      </div>

      {usage.isPending && <Spinner label="Loading usage…" />}
      {usage.isError && <ErrorBanner error={usage.error} title="Could not load usage" />}
      {usage.data && usage.data.totals.calls === 0 && (
        <Card>
          <EmptyState title="No billable calls yet">
            <p className="muted">Runs with fake providers cost nothing; live runs appear here.</p>
          </EmptyState>
        </Card>
      )}
      {usage.data && usage.data.totals.calls > 0 && (
        <>
          <div className="grid-3">
            <Card title="Committed (estimated)">
              <p className="metric">{money(usage.data.totals.committed)}</p>
              <p className="small muted">
                {usage.data.totals.runs} run(s) · {usage.data.totals.calls} metered call(s)
              </p>
            </Card>
            <Card title="Uncertain">
              <p className="metric">{money(usage.data.totals.uncertain)}</p>
              <p className="small muted">May have been billed but never confirmed (crashes, failed calls).</p>
            </Card>
            <Card title="Model tokens">
              <p className="metric">
                {(usage.data.totals.llm_input_tokens + usage.data.totals.llm_output_tokens).toLocaleString()}
              </p>
              <p className="small muted">
                {usage.data.totals.llm_input_tokens.toLocaleString()} in ·{" "}
                {usage.data.totals.llm_output_tokens.toLocaleString()} out
              </p>
            </Card>
          </div>

          <div className="grid-2">
            <Card title="By step">
              <table className="table compact">
                <thead>
                  <tr><th scope="col">Step</th><th scope="col">Calls</th><th scope="col">Tokens</th><th scope="col">Spend</th></tr>
                </thead>
                <tbody>
                  {usage.data.by_step.map((s) => (
                    <tr key={`${s.step}-${s.kind}`}>
                      <td>{s.step} <span className="muted small">{s.kind}</span></td>
                      <td>{s.calls}</td>
                      <td>{s.input_tokens + s.output_tokens || "-"}</td>
                      <td>{money(s.committed)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="By day">
              <table className="table compact">
                <thead>
                  <tr><th scope="col">Day</th><th scope="col">Calls</th><th scope="col">Spend</th></tr>
                </thead>
                <tbody>
                  {usage.data.by_day.map((d) => (
                    <tr key={d.day}>
                      <td>{d.day}</td>
                      <td>{d.calls}</td>
                      <td>{money(d.committed)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>

          <Card title="Most expensive runs">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Run</th><th scope="col">State</th><th scope="col">Started</th>
                  <th scope="col">Spend</th><th scope="col">Budget used</th>
                </tr>
              </thead>
              <tbody>
                {usage.data.top_runs.map((r) => {
                  const share = Number(r.budget) > 0 ? (Number(r.committed) / Number(r.budget)) * 100 : 0;
                  return (
                    <tr key={r.run_id}>
                      <td><Link to={`/runs/${r.run_id}`}>{r.topic}</Link></td>
                      <td><StateBadge state={r.state} /></td>
                      <td className="nowrap">{formatDateTime(r.created_at)}</td>
                      <td>{money(r.committed)}</td>
                      <td>{share.toFixed(1)}% of {money(r.budget)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        </>
      )}
      {usage.data && <p className="small muted">{usage.data.note}</p>}
    </div>
  );
}
