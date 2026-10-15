import { useState } from "react";

import { useEditPlan } from "../api/hooks";
import type { Artifact, PlanBody } from "../api/types";
import { Card, ErrorBanner } from "./ui";

/** Edit a plan as a new version. The server re-validates everything (DAG, tool policy,
 *  limits); the edited version must then be approved by its own version and digest. */
export function PlanEditor({ runId, plan, onDone }: { runId: string; plan: Artifact<PlanBody>; onDone: () => void }) {
  const edit = useEditPlan(runId);
  const [tasks, setTasks] = useState(plan.body.tasks);
  const [strategy, setStrategy] = useState(plan.body.source_strategy);
  const [assumptions, setAssumptions] = useState(plan.body.assumptions.join("\n"));

  function removeTask(taskId: string) {
    setTasks(
      tasks
        .filter((t) => t.task_id !== taskId)
        .map((t) => ({ ...t, depends_on: t.depends_on.filter((d) => d !== taskId) })),
    );
  }

  function save() {
    edit.mutate(
      {
        baseVersion: plan.version,
        plan: {
          ...plan.body,
          tasks,
          source_strategy: strategy.trim(),
          assumptions: assumptions.split("\n").map((a) => a.trim()).filter(Boolean),
        },
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card title={`Edit plan v${plan.version}`}>
      <p className="small muted">Saving creates version {plan.version + 1}. You then approve that exact version.</p>
      <ol className="tasks">
        {tasks.map((task, index) => (
          <li key={task.task_id} className="task">
            <label className="field">
              <span>
                <code>{task.task_id}</code> question
              </span>
              <textarea
                rows={2}
                maxLength={500}
                value={task.question}
                onChange={(e) =>
                  setTasks(tasks.map((t, i) => (i === index ? { ...t, question: e.target.value } : t)))
                }
              />
            </label>
            {tasks.length > 1 && (
              <button type="button" className="btn btn-ghost" onClick={() => removeTask(task.task_id)}>
                Remove task {task.task_id}
              </button>
            )}
          </li>
        ))}
      </ol>
      <label className="field">
        <span>Source strategy</span>
        <textarea rows={3} maxLength={4000} value={strategy} onChange={(e) => setStrategy(e.target.value)} />
      </label>
      <label className="field">
        <span>Assumptions (one per line)</span>
        <textarea rows={3} value={assumptions} onChange={(e) => setAssumptions(e.target.value)} />
      </label>
      {edit.isError && <ErrorBanner error={edit.error} title="Plan not saved" />}
      <div className="row end">
        <button type="button" className="btn btn-secondary" onClick={onDone} disabled={edit.isPending}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={edit.isPending || !strategy.trim()}>
          Save as v{plan.version + 1}
        </button>
      </div>
    </Card>
  );
}
