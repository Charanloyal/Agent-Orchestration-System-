import type { ClaimKind, RunEvent, RunState, Severity } from "./api/types";

export const STATE_LABELS: Record<RunState, string> = {
  QUEUED: "Queued",
  PLANNING: "Planning",
  AWAITING_PLAN_APPROVAL: "Awaiting plan approval",
  RESEARCHING: "Researching",
  WRITING: "Writing",
  REVIEWING: "Reviewing",
  AWAITING_REPORT_APPROVAL: "Awaiting report approval",
  SUCCEEDED: "Succeeded",
  NEEDS_ATTENTION: "Needs attention",
  FAILED: "Failed",
  CANCEL_REQUESTED: "Cancellation requested",
  CANCELLED: "Cancelled",
  EXPIRED: "Expired",
};

export type Tone = "neutral" | "info" | "progress" | "waiting" | "success" | "warning" | "danger";

export const STATE_TONES: Record<RunState, Tone> = {
  QUEUED: "neutral",
  PLANNING: "progress",
  AWAITING_PLAN_APPROVAL: "waiting",
  RESEARCHING: "progress",
  WRITING: "progress",
  REVIEWING: "progress",
  AWAITING_REPORT_APPROVAL: "waiting",
  SUCCEEDED: "success",
  NEEDS_ATTENTION: "warning",
  FAILED: "danger",
  CANCEL_REQUESTED: "warning",
  CANCELLED: "neutral",
  EXPIRED: "neutral",
};

export const CLAIM_KIND_LABELS: Record<ClaimKind, string> = {
  fact: "Fact",
  inference: "Inference",
  recommendation: "Recommendation",
  conflict: "Conflict",
  unknown: "Unknown",
};

export const CLAIM_KIND_TONES: Record<ClaimKind, Tone> = {
  fact: "info",
  inference: "progress",
  recommendation: "success",
  conflict: "warning",
  unknown: "neutral",
};

const num = (value: unknown): string => (typeof value === "number" ? String(value) : "?");
const str = (value: unknown): string => (typeof value === "string" ? value : "");

export const REVIEW_OUTCOMES: Record<string, string> = {
  pass: "passed",
  revise: "revision requested",
  insufficient_evidence: "more evidence needed",
};

export const SEVERITY_TONES: Record<Severity, Tone> = { blocker: "danger", major: "warning", minor: "neutral" };

/** One readable sentence per timeline event. Payloads are structured summaries only. */
export function describeEvent(event: RunEvent): string {
  const p = event.payload;
  switch (event.type) {
    case "run_created":
      return `Run created with ${num(p.questions)} research question(s)`;
    case "state_changed":
      return `${STATE_LABELS[p.to as RunState] ?? str(p.to)}${p.reason ? ` (${str(p.reason)})` : ""}`;
    case "plan_proposed":
      return `Plan v${num(p.version)} proposed with ${num(p.tasks)} task(s)${p.model ? ` by ${str(p.model)}` : ""}`;
    case "plan_edited":
      return `Plan edited by ${str(p.role)}: v${num(p.version)} created from v${num(p.from_version)}`;
    case "decision_recorded":
      return `${str(p.kind) === "plan" ? "Plan" : "Report"} v${num(p.version)} ${
        p.decision === "approve" ? "approved" : "rejected"
      } by ${str(p.role)}`;
    case "source_collected":
      return `${p.kind === "upload" ? "Document passage" : "Source"} collected for task ${str(p.task_id)} (${num(
        p.passages,
      )} passage(s))`;
    case "source_failed":
      return `Source not read for task ${str(p.task_id)}: ${str(p.reason).replaceAll("_", " ")}`;
    case "search_results_filtered":
      return `Task ${str(p.task_id)}: kept ${num(p.kept)} of ${num(p.returned)} results (source policy)`;
    case "task_completed":
      return p.stopped
        ? `Task ${str(p.task_id)} stopped: ${str(p.stopped)}`
        : `Task ${str(p.task_id)} ${str(p.status).replace("_", " ")}: ${num(p.evidence)} evidence passage(s)`;
    case "budget_exhausted":
      return `Budget exhausted at ${str(p.step)}: no further ${str(p.kind)} calls scheduled`;
    case "report_drafted":
      return `Report v${num(p.version)} drafted: ${num(p.claims)} claims, ${num(p.citations)} citations`;
    case "review_completed": {
      const f = (p.findings ?? {}) as Record<string, unknown>;
      const counts = (["blocker", "major", "minor"] as const)
        .filter((s) => typeof f[s] === "number" && (f[s] as number) > 0)
        .map((s) => `${num(f[s])} ${s}`);
      return `Review round ${num(p.round)} of report v${num(p.report_version)}: ${REVIEW_OUTCOMES[str(p.outcome)] ?? str(p.outcome)}${
        counts.length ? ` (${counts.join(", ")})` : ""
      }`;
    }
    case "report_exported":
      return `Report v${num(p.version)} exported as ${p.kind === "approved" ? "approved" : "draft"} Markdown`;
    case "retry_scheduled":
      return `Transient error; retry scheduled in ${num(p.delay_seconds)}s`;
    case "step_failed":
      return `Step ${str(p.step)} failed: ${str(p.reason)}`;
    case "tool_calls_abandoned":
      return `${num(p.count)} interrupted tool call(s) from a previous worker were marked abandoned`;
    default:
      return event.type.replaceAll("_", " ");
  }
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
