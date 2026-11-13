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
  deployment: {
    environment: string;
    agent_mode: "fake" | "llm";
    llm_model?: string | null;
    search_provider?: "fake" | "tavily" | "corpus" | "open";
  };
  is_platform_admin: boolean;
  can_create_workspace: boolean;
};

/** GET /healthz: the release (app/version.py) and the deployed commit, if known. */
export type Build = { status: "ok"; version: string; commit: string | null };

export type SignupMode = "invite" | "request" | "open";

export type AuthConfig = { provider_label: string; signup_mode: SignupMode };

export type WorkspaceInfo = { id: string; name: string; role: Role; created_at: string };

export type Member = { user_id: string; email: string | null; display_name: string; role: Role };

export type Invitation = {
  id: string;
  email: string;
  role: Role;
  invited_by: string | null;
  created_at: string;
  expires_at: string;
};

export type InviteResult = {
  status: "invited" | "added";
  invitation: Invitation | null;
  member: Member | null;
};

export type AccessRequest = {
  id: string;
  email: string;
  name: string;
  message: string | null;
  status: "pending" | "approved" | "denied";
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
};

export type AccessSource = "admin" | "request" | "invitation" | "existing_member" | "seed";

export type AccessEntry = {
  id: string;
  email: string;
  source: AccessSource;
  note: string | null;
  created_at: string;
  added_by: string | null;
};

export type AdminWorkspace = { id: string; name: string; members: number };

export type AuditEvent = {
  id: number;
  action: string;
  actor: string | null;
  target: string | null;
  details: Record<string, unknown>;
  created_at: string;
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

export type Generation = {
  provider?: string;
  model?: string;
  prompt_version?: string;
  attempts?: number;
  input_tokens?: number;
  output_tokens?: number;
  edited_from?: number;
  /** Set when the model failed and the deterministic agent did this step (ADR 0030). */
  fallback_reason?: string;
  fallback_from?: string;
};

export type Artifact<T> = {
  version: number;
  digest: string;
  created_at: string;
  body: T;
  author?: "agent" | "user";
  generation?: Generation | null;
};

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

export type Severity = "blocker" | "major" | "minor";

export type ReviewFinding = {
  finding_id: string;
  severity: Severity;
  category: string;
  source: "deterministic" | "model";
  claim_ids: string[];
  evidence_ids: string[];
  requested_action: string;
};

export type ReviewRound = {
  report_version: number;
  review_round: number;
  outcome: "pass" | "revise" | "insufficient_evidence";
  next: string;
  reviewed_at: string;
  findings: ReviewFinding[];
};

export type ExportRecord = {
  id: string;
  report_version: number;
  report_digest: string;
  kind: "approved" | "draft";
  content_sha256: string;
  created_by: string;
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
  source_kind: "web" | "corpus" | "upload";
  published_on: string | null;
  retrieved_at: string;
};

export type Source = {
  source_id: string;
  kind: "web" | "corpus" | "upload";
  url: string | null;
  upload_id: string | null;
  title: string | null;
  fetch_status: "fetched" | "failed";
  failure_reason: string | null;
  retrieved_at: string;
  published_on: string | null;
  content_sha256: string | null;
  passages: number;
};

export type UploadInfo = {
  id: string;
  filename: string;
  title: string | null;
  media_type: string;
  size_bytes: number;
  sha256: string;
  pages: number | null;
  text_chars: number;
  chunks: number;
  uploaded_by: string;
  uploaded_by_id: string;
  created_at: string;
};

export type UsageLine = {
  step: string;
  kind: "llm" | "search";
  calls: number;
  estimated: string;
  actual: string | null;
  input_tokens: number;
  output_tokens: number;
};

export type RunUsage = {
  currency: string;
  budget: string;
  committed: string;
  reconciled: string;
  outstanding: string;
  uncertain: string;
  price_schedules: string[];
  lines: UsageLine[];
  note: string;
};

export type UploadSearchHit = { upload_id: string; filename: string; locator: string | null; text: string; rank: number };

export type WorkspaceUsage = {
  days: number;
  since: string;
  totals: {
    runs: number;
    committed: string;
    reconciled: string;
    uncertain: string;
    llm_input_tokens: number;
    llm_output_tokens: number;
    calls: number;
  };
  by_day: { day: string; committed: string; calls: number }[];
  by_step: { step: string; kind: string; calls: number; committed: string; input_tokens: number; output_tokens: number }[];
  top_runs: { run_id: string; topic: string; state: RunState; created_at: string; committed: string; budget: string }[];
  note: string;
};

/** Writing Style Studio (backend/app/api/style.py). Metrics describe the text; they are not a
 *  prediction of authorship. */
export type StylePersona = "journalist" | "academic" | "executive" | "technical";
export type StyleSentence = { text: string; words: number; phrases: string[] };
export type StyleReport = {
  words: number;
  sentences: number;
  paragraphs: number;
  mean_sentence_words: number;
  sentence_length_cv: number;
  shortest_sentence: number;
  longest_sentence: number;
  vocabulary_mattr: number;
  word_entropy_bits: number;
  stock_phrases: number;
  stock_phrases_per_1000_words: number;
  paragraph_length_cv: number;
  flagged: number[];
  sentence_list: StyleSentence[];
  blocks: StyleBlock[];
};
export type StyleBlockKind = "heading" | "paragraph" | "item" | "quote" | "verbatim" | "blank";
export type StyleBlock = {
  kind: StyleBlockKind;
  prefix: string;
  text: string;
  first_sentence: number;
  sentence_count: number;
};
export type StyleChange = { before: string; after: string; rules: string[]; accepted: boolean };
export type StyleSourceInput = { text: string } | { upload_id: string };
export type StyleRewrite = {
  source: string;
  persona: StylePersona;
  original: string;
  rewritten: string;
  before: StyleReport;
  after: StyleReport;
  fact_lock: { total: number; preserved: number; missing: string[] };
  passes: number;
  changed_sentences: number;
  rejected_changes: number;
  changes: StyleChange[];
  score_before: StyleScore;
  score_after: StyleScore;
  engine: { kind: "model" | "rules"; note: string };
};
export type StyleScore = { total: number; rhythm: number; vocabulary: number; plain: number; facts: number };
export type AiProviderId = "gemini" | "groq" | "openai";
export type ThinkingLevel = "low" | "medium" | "high" | "xhigh";
export type AiModel = { id: string; label: string; free_tier: boolean | null; thinking_levels: ThinkingLevel[] };
export type AiEngine = {
  source: "workspace" | "environment" | "demo";
  live: boolean;
  label: string;
  provider: string | null;
  model: string | null;
  key_hint: string | null;
  problem: string | null;
  thinking_level?: ThinkingLevel | null;
  roles?: { role: string; model: string; thinking: string }[];
  providers: { id: AiProviderId; label: string; models: string[]; model_details?: AiModel[] }[];
};
export type AiEngineTest = { ok: boolean; latency_ms: number; model: string; detail: string };