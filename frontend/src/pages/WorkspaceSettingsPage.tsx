import { useEffect, useId, useState, type FormEvent } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router";

import {
  useChangeRole,
  useDocumentTitle,
  useInvitations,
  useInvite,
  useMembers,
  useRemoveMember,
  useRenameWorkspace,
  useRevokeInvitation,
  useWorkspace,
} from "../api/hooks";
import type { Invitation, Me, Member, Role } from "../api/types";
import { AiEngineCard } from "../components/AiEngineCard";
import { notify } from "../components/toast";
import { Badge, Card, ConfirmButton, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { formatDate, ROLE_HELP, ROLE_LABELS } from "../format";

const ROLES: Role[] = ["analyst", "reviewer", "admin"];

/** Workspace admins: the name, who is in the workspace with which role, and invitations. */
export function WorkspaceSettingsPage() {
  const { workspaceId = "" } = useParams();
  const me = useOutletContext<Me>();
  const membership = me.memberships.find((m) => m.workspace_id === workspaceId);
  useDocumentTitle("Workspace settings");

  if (membership?.role !== "admin") {
    return (
      <Card>
        <EmptyState title="Admins only">
          <p className="muted">Workspace settings are managed by the workspace's admins.</p>
        </EmptyState>
      </Card>
    );
  }
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Workspace settings</h1>
          <p className="muted">
            The engine {membership.workspace_name} runs on, who can use it, and what each person can do.
          </p>
        </div>
      </div>
      <AiEngineCard workspaceId={workspaceId} />
      <div className="settings-grid">
        <div className="stack">
          <RenameCard workspaceId={workspaceId} />
          <MembersCard workspaceId={workspaceId} me={me} />
        </div>
        <div className="stack">
          <InviteCard workspaceId={workspaceId} />
          <InvitationsCard workspaceId={workspaceId} />
        </div>
      </div>
    </div>
  );
}

function RenameCard({ workspaceId }: { workspaceId: string }) {
  const workspace = useWorkspace(workspaceId);
  const rename = useRenameWorkspace(workspaceId);
  const [name, setName] = useState("");
  useEffect(() => {
    if (workspace.data) setName(workspace.data.name);
  }, [workspace.data]);
  const unchanged = !workspace.data || name.trim() === workspace.data.name;

  return (
    <Card title="Name">
      <form
        className="row wrap"
        onSubmit={(event) => {
          event.preventDefault();
          rename.mutate(name.trim());
        }}
      >
        <label className="field grow">
          <span>Workspace name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
        </label>
        <button type="submit" className="btn btn-secondary" disabled={unchanged || !name.trim() || rename.isPending}>
          Save name
        </button>
      </form>
    </Card>
  );
}

function MembersCard({ workspaceId, me }: { workspaceId: string; me: Me }) {
  const members = useMembers(workspaceId);
  const changeRole = useChangeRole(workspaceId);
  const remove = useRemoveMember(workspaceId);
  const navigate = useNavigate();
  const count = members.data?.length;

  return (
    <Card title="Members" actions={count !== undefined && <span className="muted small">{count} total</span>}>
      {members.isPending && <Spinner label="Loading members…" />}
      {members.isError && <ErrorBanner error={members.error} title="Could not load members" />}
      {members.data && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Workspace members</caption>
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Role</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {members.data.map((member) => (
                <MemberRow
                  key={member.user_id}
                  member={member}
                  self={member.user_id === me.user_id}
                  busy={changeRole.isPending || remove.isPending}
                  onRole={(role) => changeRole.mutate({ userId: member.user_id, role })}
                  onRemove={() =>
                    remove.mutate(member.user_id, {
                      onSuccess: () => {
                        if (member.user_id === me.user_id) navigate("/", { replace: true });
                      },
                    })
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="role-help">
        <summary>What can each role do?</summary>
        <ul>
          {ROLES.map((role) => (
            <li key={role}>
              <strong>{ROLE_LABELS[role]}</strong>: {ROLE_HELP[role]}.
            </li>
          ))}
        </ul>
      </details>
    </Card>
  );
}

function MemberRow({
  member,
  self,
  busy,
  onRole,
  onRemove,
}: {
  member: Member;
  self: boolean;
  busy: boolean;
  onRole: (role: Role) => void;
  onRemove: () => void;
}) {
  const name = self ? `${member.display_name} (you)` : member.display_name;
  return (
    <tr>
      <td>
        <div>{name}</div>
        {member.email && <div className="muted small">{member.email}</div>}
      </td>
      <td>
        <select
          aria-label={`Role for ${member.display_name}`}
          value={member.role}
          disabled={busy}
          onChange={(e) => onRole(e.target.value as Role)}
        >
          {ROLES.map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role]}
            </option>
          ))}
        </select>
      </td>
      <td className="cell-actions">
        <ConfirmButton
          label="Remove"
          ariaLabel={`Remove ${member.display_name}`}
          prompt={self ? "Remove yourself from this workspace?" : `Remove ${member.display_name}?`}
          confirmLabel="Yes, remove"
          pending={busy}
          className="btn btn-ghost"
          onConfirm={onRemove}
        />
      </td>
    </tr>
  );
}

function InviteCard({ workspaceId }: { workspaceId: string }) {
  const invite = useInvite(workspaceId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  const roleId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    invite.mutate(
      { email: email.trim(), role },
      {
        onSuccess: (result) => {
          setEmail("");
          notify(
            "success",
            result.status === "added"
              ? `${result.member?.display_name ?? "They"} already had an account and is now a member.`
              : `Invitation created for ${result.invitation?.email}. They join when they first sign in.`,
          );
        },
      },
    );
  };

  return (
    <Card title="Invite people">
      <form onSubmit={submit}>
        <div className="row wrap align-end">
          <label className="field grow">
            <span>Email address</span>
            <input type="email" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <div className="field">
            <label htmlFor={roleId}>Role</label>
            <select id={roleId} value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="btn btn-primary field-button" disabled={invite.isPending}>
            {invite.isPending ? "Inviting…" : "Invite"}
          </button>
        </div>
        <p className="muted small">
          {ROLE_LABELS[role]}: {ROLE_HELP[role]}. No email is sent: tell them to sign in at{" "}
          <code>{window.location.origin}</code> with this address. Invitations expire after 14 days.
        </p>
        {invite.isError && <ErrorBanner error={invite.error} title="Not invited" />}
      </form>
    </Card>
  );
}

function InvitationsCard({ workspaceId }: { workspaceId: string }) {
  const invitations = useInvitations(workspaceId);
  const revoke = useRevokeInvitation(workspaceId);
  return (
    <Card title="Pending invitations">
      {invitations.isPending && <Spinner label="Loading invitations…" />}
      {invitations.isError && <ErrorBanner error={invitations.error} title="Could not load invitations" />}
      {invitations.data?.length === 0 && <p className="muted">No pending invitations.</p>}
      {invitations.data && invitations.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Pending invitations</caption>
            <thead>
              <tr>
                <th scope="col">Invitation</th>
                <th scope="col">Role</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {invitations.data.map((invitation) => (
                <InvitationRow
                  key={invitation.id}
                  invitation={invitation}
                  pending={revoke.isPending}
                  onRevoke={() => revoke.mutate(invitation.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function InvitationRow({
  invitation,
  pending,
  onRevoke,
}: {
  invitation: Invitation;
  pending: boolean;
  onRevoke: () => void;
}) {
  const expired = new Date(invitation.expires_at).getTime() < Date.now();
  return (
    <tr>
      <td>
        <div>{invitation.email}</div>
        <div className="muted small">
          {invitation.invited_by && <>Invited by {invitation.invited_by} · </>}
          {expired ? <Badge tone="warning">Expired</Badge> : <>expires {formatDate(invitation.expires_at)}</>}
        </div>
      </td>
      <td>{ROLE_LABELS[invitation.role]}</td>
      <td className="cell-actions">
        <ConfirmButton
          label="Revoke"
          ariaLabel={`Revoke the invitation for ${invitation.email}`}
          prompt={`Revoke the invitation for ${invitation.email}?`}
          confirmLabel="Yes, revoke"
          pending={pending}
          className="btn btn-ghost"
          onConfirm={onRevoke}
        />
      </td>
    </tr>
  );
}
