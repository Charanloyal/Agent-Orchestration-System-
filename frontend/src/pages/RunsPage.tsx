import { Link, useOutletContext, useParams } from "react-router";

import { useDocumentTitle, useRuns } from "../api/hooks";
import type { Me } from "../api/types";
import { Card, EmptyState, ErrorBanner, Spinner, StateBadge } from "../components/ui";
import { formatDateTime } from "../format";

export function RunsPage() {
  useDocumentTitle("Runs");
  const { workspaceId = "" } = useParams();
  const me = useOutletContext<Me>();
  const role = me.memberships.find((m) => m.workspace_id === workspaceId)?.role;
  const runs = useRuns(workspaceId);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Research runs</h1>
          <p className="muted">Briefs, their approval status, and outcomes in this workspace.</p>
        </div>
        {role !== "reviewer" && (
          <Link className="btn btn-primary" to={`/w/${workspaceId}/new`}>
            New brief
          </Link>
        )}
      </div>
      <Card>
        {runs.isPending && <Spinner />}
        {runs.isError && <ErrorBanner error={runs.error} title="Could not load runs" />}
        {runs.data && runs.data.length === 0 && (
          <EmptyState title="No runs yet">
            <p className="muted">Submit a research brief to start the planner.</p>
          </EmptyState>
        )}
        {runs.data && runs.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <caption className="visually-hidden">Research runs</caption>
              <thead>
                <tr>
                  <th scope="col">Topic</th>
                  <th scope="col">State</th>
                  <th scope="col" className="hide-narrow">Created by</th>
                  <th scope="col" className="hide-narrow">Created</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link to={`/runs/${run.id}`}>{run.topic}</Link>
                    </td>
                    <td>
                      <StateBadge state={run.state} />
                    </td>
                    <td className="hide-narrow">{run.created_by}</td>
                    <td className="nowrap hide-narrow">{formatDateTime(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
