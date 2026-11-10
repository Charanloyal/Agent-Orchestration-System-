import { Link, useOutletContext, useParams } from "react-router";

import { useAuditLog, useDocumentTitle } from "../api/hooks";
import type { AuditEvent, Me } from "../api/types";
import { Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { formatDateTime } from "../format";

const ACTION_LABELS: Record<string, string> = {
  "run.create": "submitted a brief",
  "run.cancel": "cancelled a run",
  "run.retry": "retried a failed run",
  "run.delete": "deleted a run",
  "run.retention_delete": "Retention removed a finished run",
  "plan.approve": "approved a plan",
  "plan.reject": "rejected a plan",
  "plan.edit": "edited a plan",
  "report.approve": "approved a report",
  "report.reject": "rejected a report",
  "report.exported": "exported a report",
  "upload.create": "uploaded a document",
  "upload.rejected": "uploaded a document that was rejected",
  "upload.delete": "deleted a document",
  "upload.retention_delete": "Retention removed a document",
  "member.add": "added a member",
  "member.role_change": "changed a member's role",
  "member.remove": "removed a member",
  "workspace.create": "created the workspace",
};

function describe(event: AuditEvent): string {
  const label = ACTION_LABELS[event.action] ?? event.action.replaceAll(".", " ").replaceAll("_", " ");
  if (!event.actor) return label.charAt(0).toUpperCase() + label.slice(1);
  return `${event.actor} ${label}`;
}

/** Workspace security log for admins (ADR 0019): append-only, ids and counts only. */
export function ActivityPage() {
  const { workspaceId = "" } = useParams();
  const me = useOutletContext<Me>();
  const role = me.memberships.find((m) => m.workspace_id === workspaceId)?.role;
  const audit = useAuditLog(workspaceId, role === "admin");
  useDocumentTitle("Activity");

  if (role !== "admin") {
    return (
      <Card>
        <EmptyState title="Admins only">
          <p className="muted">The activity log is visible to workspace admins.</p>
        </EmptyState>
      </Card>
    );
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Activity</h1>
          <p className="muted">
            Security-relevant actions in this workspace, newest first. Entries cannot be edited or deleted and
            remain after the runs they mention are deleted.
          </p>
        </div>
      </div>
      {audit.isPending && <Spinner label="Loading activity…" />}
      {audit.isError && <ErrorBanner error={audit.error} title="Could not load activity" />}
      {audit.data && audit.data.length === 0 && (
        <Card>
          <EmptyState title="No activity yet" />
        </Card>
      )}
      {audit.data && audit.data.length > 0 && (
        <Card>
          <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Workspace activity log</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">What</th>
                <th scope="col" className="hide-narrow">Target</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.map((event) => (
                <tr key={event.id}>
                  <td className="nowrap">{formatDateTime(event.created_at)}</td>
                  <td>{describe(event)}</td>
                  <td className="small hide-narrow">
                    {event.target && /^(run|plan|report)\./.test(event.action) && !event.action.endsWith("delete") ? (
                      <Link to={`/runs/${event.target}`}>
                        <code>{event.target.slice(0, 8)}</code>
                      </Link>
                    ) : event.target ? (
                      <code title={event.target}>{event.target.slice(0, 8)}</code>
                    ) : (
                      <span className="muted">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </Card>
      )}
    </div>
  );
}
