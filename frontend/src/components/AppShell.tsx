import { Link, NavLink, Navigate, Outlet, useLocation, useParams } from "react-router";

import { useMe, useSignOut } from "../api/hooks";
import type { Me } from "../api/types";
import { ErrorBanner, Spinner } from "./ui";

/** Gate for signed-in pages. Unauthenticated users go to /signin and come back afterwards. */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return <Spinner label="Checking your session…" />;
  if (me.isError) return <ErrorBanner error={me.error} title="Could not load your session" />;
  if (!me.data) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/signin?next=${next}`} replace />;
  }
  return <AppShell me={me.data} />;
}

function AppShell({ me }: { me: Me }) {
  const { workspaceId } = useParams();
  const signOut = useSignOut();
  const current = me.memberships.find((m) => m.workspace_id === workspaceId) ?? me.memberships[0];

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Agent Orchestration System home">
          <span className="brand-mark" aria-hidden="true">◆</span> Agent Orchestration
        </Link>
        {current && (
          <nav className="topnav" aria-label="Workspace">
            <NavLink to={`/w/${current.workspace_id}/runs`} end>
              Runs
            </NavLink>
            {current.role !== "reviewer" && <NavLink to={`/w/${current.workspace_id}/new`}>New brief</NavLink>}
            <NavLink to={`/w/${current.workspace_id}/documents`}>Documents</NavLink>
            {current.role !== "reviewer" && <NavLink to={`/w/${current.workspace_id}/usage`}>Usage</NavLink>}
          </nav>
        )}
        <div className="topbar-right">
          {me.memberships.length > 1 && current && (
            <WorkspaceSwitcher me={me} currentId={current.workspace_id} />
          )}
          {current && me.memberships.length <= 1 && <span className="muted">{current.workspace_name}</span>}
          <span className="user" title={me.email ?? undefined}>
            {me.display_name}
            {current && <span className="muted small"> · {current.role}</span>}
          </span>
          <button type="button" className="btn btn-ghost" onClick={() => signOut.mutate()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        {me.memberships.length === 0 ? (
          <div className="banner">
            You are signed in but not a member of any workspace yet. Ask a workspace admin to add{" "}
            <strong>{me.email}</strong>.
          </div>
        ) : (
          <Outlet context={me} />
        )}
      </main>
    </div>
  );
}

function WorkspaceSwitcher({ me, currentId }: { me: Me; currentId: string }) {
  return (
    <select
      aria-label="Workspace"
      value={currentId}
      onChange={(event) => window.location.assign(`/w/${event.target.value}/runs`)}
    >
      {me.memberships.map((m) => (
        <option key={m.workspace_id} value={m.workspace_id}>
          {m.workspace_name}
        </option>
      ))}
    </select>
  );
}

export function HomeRedirect() {
  const me = useMe();
  if (me.isPending) return <Spinner />;
  const first = me.data?.memberships[0];
  return <Navigate to={first ? `/w/${first.workspace_id}/runs` : "/signin"} replace />;
}
