import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";

import { keys, useCreateWorkspace, useDocumentTitle } from "../api/hooks";
import type { Me } from "../api/types";
import { Card, ErrorBanner } from "../components/ui";

const STEPS = [
  ["Write a brief", "An analyst describes the topic, the audience and the questions to answer."],
  ["Approve the plan", "Agents propose research tasks; nothing is researched until a person approves them."],
  ["Research and draft", "Agents collect sources and write a report where every claim cites its evidence."],
  ["Review", "A reviewer checks claims against the quoted evidence and approves, or asks for a revision."],
  ["Export", "The approved report downloads as Markdown with its sources and approval record."],
] as const;

/** First page for someone signed in without a workspace: start one, or find out how to join. */
export function OnboardingPage({ me }: { me: Me }) {
  useDocumentTitle("Welcome");
  const create = useCreateWorkspace();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(name.trim(), { onSuccess: (workspace) => navigate(`/w/${workspace.id}/runs`) });
  };

  return (
    <div className="stack onboarding">
      <div className="page-header">
        <div>
          <h1>Welcome, {me.display_name}</h1>
          <p className="muted">
            You're signed in{me.email ? <> as <strong>{me.email}</strong></> : null}, but you're not part of a
            workspace yet.
          </p>
        </div>
      </div>
      <div className="grid-2">
        {me.can_create_workspace && (
          <Card title="Start a workspace">
            <p className="muted">
              A workspace holds a team's briefs, runs, reports and documents. You'll be its admin and can invite
              people with the roles they need.
            </p>
            <form onSubmit={submit}>
              <label className="field">
                <span>Workspace name</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={100}
                  required
                  placeholder="e.g. Platform research"
                />
              </label>
              {create.isError && <ErrorBanner error={create.error} title="The workspace was not created" />}
              <button type="submit" className="btn btn-primary" disabled={!name.trim() || create.isPending}>
                {create.isPending ? "Creating…" : "Create workspace"}
              </button>
            </form>
          </Card>
        )}
        <Card title="Join your team's workspace">
          <p>
            Ask a workspace admin to invite <strong>{me.email ?? "the email address you sign in with"}</strong>.
            You're added as soon as they do.
          </p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void client.invalidateQueries({ queryKey: keys.me })}
          >
            Check again
          </button>
        </Card>
      </div>
      {me.is_platform_admin && (
        <Card title="Manage access to this deployment">
          <p className="muted">
            You're a platform admin: you approve access requests and keep the list of people who may sign in.
          </p>
          <Link className="btn btn-secondary" to="/admin/access">
            Open access settings
          </Link>
        </Card>
      )}
      <Card title="How a research run works">
        <ol className="how-it-works">
          {STEPS.map(([title, text]) => (
            <li key={title}>
              <strong>{title}.</strong> <span className="muted">{text}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
