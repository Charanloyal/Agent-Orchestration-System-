import { useId, useState, type FormEvent } from "react";
import { useOutletContext } from "react-router";

import {
  useAccessList,
  useAccessRequests,
  useAddAccess,
  useAdminWorkspaces,
  useDecideRequest,
  useDocumentTitle,
  useRemoveAccess,
} from "../api/hooks";
import type { AccessEntry, AccessRequest, AdminWorkspace, Me, Role } from "../api/types";
import { notify } from "../components/toast";
import { Badge, Card, ConfirmButton, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { ACCESS_SOURCE_LABELS, formatDate, formatDateTime, ROLE_LABELS } from "../format";
import { NotFoundPage } from "./NotFoundPage";

/** Platform admins: who may sign in to this deployment (ADR 0021). Everyone else sees the
 *  same "not found" page as for any unknown address. */
export function AdminAccessPage() {
  const me = useOutletContext<Me>();
  return me.is_platform_admin ? <AdminAccess /> : <NotFoundPage />;
}

function AdminAccess() {
  useDocumentTitle("Access");
  return (
    <div className="stack narrow">
      <div className="page-header">
        <div>
          <h1>Access</h1>
          <p className="muted">
            Decide who can sign in to this deployment. Workspace admins can also invite people into their own
            workspaces; platform admins and allowlisted domains are set in the deployment's configuration.
          </p>
        </div>
      </div>
      <RequestsCard />
      <AccessListCard />
    </div>
  );
}

function RequestsCard() {
  const pending = useAccessRequests("pending");
  const workspaces = useAdminWorkspaces();
  const [showDecided, setShowDecided] = useState(false);
  const decided = useAccessRequests("decided", showDecided);
  const count = pending.data?.length;

  return (
    <Card title="Access requests" actions={count ? <Badge tone="waiting">{count} pending</Badge> : null}>
      {pending.isPending && <Spinner label="Loading requests…" />}
      {pending.isError && <ErrorBanner error={pending.error} title="Could not load requests" />}
      {pending.data?.length === 0 && (
        <EmptyState title="No pending requests">
          <p className="muted small">New requests from the sign-in page appear here.</p>
        </EmptyState>
      )}
      {pending.data && pending.data.length > 0 && (
        <ul className="request-list" aria-label="Pending access requests">
          {pending.data.map((request) => (
            <RequestItem key={request.id} request={request} workspaces={workspaces.data ?? []} />
          ))}
        </ul>
      )}
      <button type="button" className="link-button small" onClick={() => setShowDecided((v) => !v)} aria-expanded={showDecided}>
        {showDecided ? "Hide decided requests" : "Show decided requests"}
      </button>
      {showDecided && decided.isPending && <Spinner label="Loading decided requests…" />}
      {showDecided && decided.data?.length === 0 && <p className="muted small">No decided requests yet.</p>}
      {showDecided && decided.data && decided.data.length > 0 && (
        <div className="table-wrap">
          <table className="table compact">
            <caption className="visually-hidden">Decided access requests</caption>
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">Decision</th>
                <th scope="col" className="hide-narrow">By</th>
                <th scope="col" className="hide-narrow">When</th>
              </tr>
            </thead>
            <tbody>
              {decided.data.map((r) => (
                <tr key={r.id}>
                  <td>{r.email}</td>
                  <td>
                    <Badge tone={r.status === "approved" ? "success" : "neutral"}>
                      {r.status === "approved" ? "Approved" : "Denied"}
                    </Badge>
                  </td>
                  <td className="hide-narrow">{r.decided_by ?? "-"}</td>
                  <td className="nowrap hide-narrow">{r.decided_at ? formatDateTime(r.decided_at) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RequestItem({ request, workspaces }: { request: AccessRequest; workspaces: AdminWorkspace[] }) {
  const decide = useDecideRequest();
  const [workspaceId, setWorkspaceId] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  const ids = useId();
  const workspaceName = workspaces.find((w) => w.id === workspaceId)?.name;

  // mutateAsync, not per-call callbacks: a decided request leaves the pending list while the lists
  // reload, which unmounts this row, and React Query skips callbacks of an unmounted observer.
  // Errors are already reported by the global mutation cache (meta.error).
  const decideThen = (input: Parameters<typeof decide.mutateAsync>[0], message: string) =>
    decide.mutateAsync(input).then(
      () => notify("success", message),
      () => {},
    );

  const approve = (event: FormEvent) => {
    event.preventDefault();
    void decideThen(
      { id: request.id, decision: "approve", workspaceId: workspaceId || null, role },
      workspaceName
        ? `Approved ${request.email}; they join ${workspaceName} as ${ROLE_LABELS[role].toLowerCase()} when they sign in.`
        : `Approved ${request.email}; they can sign in now.`,
    );
  };

  return (
    <li className="request">
      <div className="request-head">
        <div>
          <strong>{request.name}</strong> <span className="muted">&lt;{request.email}&gt;</span>
        </div>
        <span className="muted small nowrap">Asked {formatDateTime(request.created_at)}</span>
      </div>
      {request.message && <blockquote className="request-message">{request.message}</blockquote>}
      <form className="row wrap align-end" onSubmit={approve} aria-label={`Decide on ${request.email}`}>
        <div className="field">
          <label htmlFor={`${ids}-workspace`}>Add to workspace</label>
          <select id={`${ids}-workspace`} value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
            <option value="">No workspace yet</option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${ids}-role`}>Role</label>
          <select
            id={`${ids}-role`}
            value={role}
            disabled={!workspaceId}
            onChange={(e) => setRole(e.target.value as Role)}
          >
            {(["analyst", "reviewer", "admin"] as const).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn btn-primary field-button" disabled={decide.isPending}>
          Approve
        </button>
        <span className="field-button">
          <ConfirmButton
            label="Deny"
            ariaLabel={`Deny ${request.email}`}
            prompt={`Deny ${request.email}?`}
            confirmLabel="Yes, deny"
            pending={decide.isPending}
            onConfirm={() => void decideThen({ id: request.id, decision: "deny" }, `Denied ${request.email}.`)}
          />
        </span>
      </form>
    </li>
  );
}

function AccessListCard() {
  const list = useAccessList();
  const add = useAddAccess();
  const remove = useRemoveAccess();
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate(
      { email: email.trim(), note: note.trim() || undefined },
      {
        onSuccess: () => {
          setEmail("");
          setNote("");
        },
      },
    );
  };

  return (
    <Card title="Access list" actions={list.data && <span className="muted small">{list.data.length} people</span>}>
      <p className="muted small">
        People on this list can sign in. Removing someone signs them out everywhere; their workspace
        memberships and work stay, so you can restore access later.
      </p>
      <form className="row wrap align-end" onSubmit={submit}>
        <label className="field grow">
          <span>Email address</span>
          <input type="email" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field grow">
          <span>
            Note <span className="muted">(optional)</span>
          </span>
          <input maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-secondary field-button" disabled={add.isPending}>
          Add
        </button>
      </form>
      {add.isError && <ErrorBanner error={add.error} title="Not added" />}
      {list.isPending && <Spinner label="Loading the access list…" />}
      {list.isError && <ErrorBanner error={list.error} title="Could not load the access list" />}
      {list.data?.length === 0 && <p className="muted">Nobody is on the access list yet.</p>}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Access list</caption>
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">How</th>
                <th scope="col" className="hide-narrow">Added</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((entry) => (
                <EntryRow key={entry.id} entry={entry} pending={remove.isPending} onRemove={() => remove.mutate(entry.id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function EntryRow({ entry, pending, onRemove }: { entry: AccessEntry; pending: boolean; onRemove: () => void }) {
  return (
    <tr>
      <td>
        <div>{entry.email}</div>
        {entry.note && <div className="muted small">{entry.note}</div>}
      </td>
      <td className="small">
        {ACCESS_SOURCE_LABELS[entry.source]}
        {entry.added_by && <span className="muted"> · {entry.added_by}</span>}
      </td>
      <td className="nowrap small hide-narrow">{formatDate(entry.created_at)}</td>
      <td className="cell-actions">
        <ConfirmButton
          label="Remove"
          ariaLabel={`Remove access for ${entry.email}`}
          prompt={`Remove ${entry.email}? They are signed out everywhere.`}
          confirmLabel="Yes, remove access"
          pending={pending}
          className="btn btn-ghost"
          onConfirm={onRemove}
        />
      </td>
    </tr>
  );
}
