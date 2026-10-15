// Types mirroring the backend API (backend/app/api/*.py). Keep in sync with OpenAPI.

export type Role = "analyst" | "reviewer" | "admin";

export type RunState =
  | "QUEUED"
  | "PLANNING"
  | "AWAITING_PLAN_APPROVAL"
  | "RESEARCHING"
  | "WRITING"
  | "REVIEWING"
  | "AWAITING_REPORT_APPROVAL"
  | "SUCCEEDED"
  | "NEEDS_ATTENTION"
  | "FAILED"
  | "CANCEL_REQUESTED"
  | "CANCELLED"
  | "EXPIRED";

export const TERMINAL_STATES: ReadonlySet<RunState> = new Set([
  "SUCCEEDED",
  "NEEDS_ATTENTION",
  "FAILED",
  "CANCELLED",
  "EXPIRED",
]);

export type Membership = { workspace_id: string; workspace_name: string; role: Role };

export type Me = {
  user_id: string;
  email: string | null;
  display_name: string;
  csrf_token: string;
  memberships: Membership[];
};

export type SourceType = "public_web" | "vendor_docs" | "uploaded_documents";

export type BriefInput = {
  topic: string;
  audience: string;
  research_questions: string[];
  source_policy: {
    allowed_source_types: SourceType[];
    allowed_domains: string[];
    blocked_domains: string[];
    date_cutoff?: string | null;
  };
  output_format: "markdown";
  budget: { currency: "USD"; max_estimated_cost: string };
  limits: {
    max_tasks: number;
    max_parallel_tasks: number;
    max_tool_calls: number;
    max_review_rounds: number;
    deadline_minutes: number;
  };
};

export type RunSummary = {
  id: string;
  workspace_id: string;
  state: RunState;
  topic: string;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type PlanTask = {
  task_id: string;
  question: string;
  depends_on: string[];
  tools: string[];
  expected_evidence: string;
  section_ids: string[];
};

export type PlanBody = {
  plan_version: number;
  tasks: PlanTask[];
  outline: { section_id: string; title: string; purpose: string }[];
  source_strategy: string;
  assumptions: string[];
};

export type ClaimKind = "fact" | "inference" | "recommendation" | "conflict" | "unknown";

export type Claim = { claim_id: string; kind: ClaimKind; text: string; evidence_ids: string[] };

export type ReportBody = {
  report_version: number;
  plan_version: number;
  sections: { section_id: string; title: string; claims: Claim[] }[];
};

export type Artifact<T> = { version: number; digest: string; created_at: string; body: T };

export type Decision = {
  id: string;
  kind: "plan" | "report";
  version: number;
  decision: "approve" | "reject";
  comment: string | null;
  decided_by: string;
  decided_at: string;
};

export type RunDetail = RunSummary & {
  brief: BriefInput;
  deadline_at: string;
  outcome_reason: string | null;
  job: {
    state: string;
    waiting_for: "plan" | "report" | null;
    attempts: number;
    wait_deadline_at: string | null;
    last_error: string | null;
  };
  pending_decision: { kind: "plan" | "report"; version: number; digest: string } | null;
  plan: Artifact<PlanBody> | null;
  report: Artifact<ReportBody> | null;
  decisions: Decision[];
};

export type RunEvent = {
  id: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Evidence = {
  evidence_id: string;
  task_id: string;
  locator: string | null;
  text: string;
  text_sha256: string;
  source_id: string;
  source_title: string | null;
  source_url: string | null;
  published_on: string | null;
  retrieved_at: string;
};
