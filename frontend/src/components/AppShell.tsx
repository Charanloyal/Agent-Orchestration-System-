import { Link, NavLink, Navigate, Outlet, useLocation, useOutletContext, useParams } from "react-router";

import { useAdminSummary, useBuild, useMe, useSignOut } from "../api/hooks";
import type { Me } from "../api/types";
import { OnboardingPage } from "../pages/OnboardingPage";
import { ThemeToggle } from "../theme";
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
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Agent Orchestration System home">
          <span className="brand-mark" aria-hidden="true">◆</span>
          <span className="brand-name">Agent Orchestration</span>
        </Link>
        {current && (
          <nav className="topnav" aria-label="Workspace">
            <NavLink to={`/w/${current.workspace_id}/runs`} end>
              Runs
            </NavLink>
            {current.role !== "reviewer" && <NavLink to={`/w/${current.workspace_id}/new`}>New brief</NavLink>}
            <NavLink to={`/w/${current.workspace_id}/documents`}>Documents</NavLink>
            <NavLink to={`/w/${current.workspace_id}/style`}>Style studio</NavLink>
            <NavLink to={`/w/${current.workspace_id}/agents`}>Agents</NavLink>
            {current.role !== "reviewer" && <NavLink to={`/w/${current.workspace_id}/usage`}>Usage</NavLink>}
            {current.role === "admin" && <NavLink to={`/w/${current.workspace_id}/activity`}>Activity</NavLink>}
            {current.role === "admin" && <NavLink to={`/w/${current.workspace_id}/settings`}>Settings</NavLink>}
          </nav>
        )}
        <div className="topbar-right">
          <EnginePill me={me} workspaceId={current?.workspace_id} />
          {me.is_platform_admin && <AccessLink />}
          {me.memberships.length > 1 && current && (
            <WorkspaceSwitcher me={me} currentId={current.workspace_id} />
          )}
          {current && me.memberships.length <= 1 && <span className="muted workspace-name">{current.workspace_name}</span>}
          <span className="user" title={me.email ?? undefined}>
            {me.display_name}
            {current && <span className="muted small"> · {current.role}</span>}
          </span>
          <ThemeToggle />
          <button type="button" className="btn btn-ghost" onClick={() => signOut.mutate()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content" id="main" tabIndex={-1}>
        <Outlet context={me} />
      </main>
      <BuildFooter />
    </div>
  );
}

/** Which engine writes the reports: a language model (its name) or the deterministic demo
 *  agents. Links to the agents page, which explains the difference. */
function EnginePill({ me, workspaceId }: { me: Me; workspaceId?: string }) {
  const live = me.deployment?.agent_mode === "llm";
  const text = live ? `Model agents${me.deployment.llm_model ? ` · ${me.deployment.llm_model}` : ""}` : "Demo agents";
  const title = live
    ? `Reports are written by a language model (${me.deployment.llm_model ?? "configured model"}), with citations checked in code.`
    : "This deployment uses deterministic demo agents, not a language model. Reports show the workflow, not model quality.";
  const body = (
    <>
      <span className="engine-dot" aria-hidden="true" />
      <span className="engine-label">{text}</span>
    </>
  );
  const className = `engine-pill ${live ? "engine-live" : "engine-demo"}`;
  return workspaceId ? (
    <Link to={`/w/${workspaceId}/agents`} className={className} title={title}>
      {body}
    </Link>
  ) : (
    <span className={className} title={title}>
      {body}
    </span>
  );
}

/** The running release and commit, so a demo shows exactly which build is live. */
function BuildFooter() {
  const build = useBuild().data;
  return (
    <footer className="build-footer small muted">
      {build && (build.commit ? `v${build.version} · ${build.commit.slice(0, 7)}` : `v${build.version}`)}
    </footer>
  );
}

/** Platform admins: deployment-wide access, with the number of requests waiting. */
function AccessLink() {
  const summary = useAdminSummary(true);
  const pending = summary.data?.pending_requests ?? 0;
  const label = pending > 0 ? `Access, ${pending} pending ${pending === 1 ? "request" : "requests"}` : undefined;
  return (
    <NavLink to="/admin/access" className="access-link" aria-label={label}>
      Access
      {pending > 0 && (
        <span className="badge badge-waiting" aria-hidden="true">
          {pending}
        </span>
      )}
    </NavLink>
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

/** `/`: the first workspace's runs, or onboarding for people without a workspace yet. */
export function HomeRedirect() {
  const me = useOutletContext<Me>();
  const first = me.memberships[0];
  if (!first) return <OnboardingPage me={me} />;
  return <Navigate to={`/w/${first.workspace_id}/runs`} replace />;
}
