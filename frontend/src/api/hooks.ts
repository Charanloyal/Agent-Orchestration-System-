import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, download, saveBlob, setCsrfToken } from "./client";
import { beginSignOut, signInPath } from "./session";
import type {
  AccessEntry,
  AccessRequest,
  AdminWorkspace,
  Artifact,
  AuditEvent,
  AuthConfig,
  Build,
  BriefInput,
  Decision,
  Evidence,
  ExportRecord,
  Invitation,
  InviteResult,
  Me,
  Member,
  PlanBody,
  ReportBody,
  ReviewRound,
  Role,
  RunDetail,
  RunEvent,
  RunSummary,
  RunUsage,
  Source,
  StylePersona,
  StyleRewrite,
  StyleSourceInput,
  UploadInfo,
  UploadSearchHit,
  WorkspaceInfo,
  WorkspaceUsage,
} from "./types";
import { TERMINAL_STATES } from "./types";

export const keys = {
  me: ["me"] as const,
  runs: (workspaceId: string) => ["runs", workspaceId] as const,
  run: (runId: string) => ["run", runId] as const,
  evidence: (runId: string) => ["evidence", runId] as const,
  workspace: (workspaceId: string) => ["workspace", workspaceId] as const,
  admin: ["admin"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        const me = await api<Me>("/api/v1/auth/me");
        setCsrfToken(me.csrf_token);
        return me;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setCsrfToken(null);
          return null;
        }
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useBuild() {
  return useQuery({
    queryKey: ["build"],
    queryFn: () => api<Build>("/healthz"),
    staleTime: Infinity,
    retry: false,
  });
}

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
    onMutate: () => beginSignOut(),
    onSettled: () => {
      setCsrfToken(null);
      client.clear();
      window.location.assign(signInPath("signed_out"));
    },
  });
}

/** Public: the sign-in button label and whether access requests are taken. */
export function useAuthConfig() {
  return useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api<AuthConfig>("/api/v1/auth/config"),
    staleTime: Infinity,
    retry: 1,
  });
}

export type AccessRequestInput = { email: string; name: string; message?: string };

export function useRequestAccess() {
  return useMutation({
    mutationFn: (body: AccessRequestInput) =>
      api<{ status: "received"; message: string }>("/api/v1/access-requests", { method: "POST", body }),
  });
}

export function useCreateWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api<WorkspaceInfo>("/api/v1/workspaces", { method: "POST", body: { name } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.me }),
    meta: { success: "Workspace created" },
  });
}

export function useWorkspace(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: keys.workspace(workspaceId),
    queryFn: () => api<WorkspaceInfo>(`/api/v1/workspaces/${workspaceId}`),
    enabled,
  });
}

export function useRenameWorkspace(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api<WorkspaceInfo>(`/api/v1/workspaces/${workspaceId}`, { method: "PATCH", body: { name } }),
    onSuccess: (workspace) => {
      client.setQueryData(keys.workspace(workspaceId), workspace);
      void client.invalidateQueries({ queryKey: keys.me });
    },
    meta: { success: "Workspace renamed", error: "Could not rename the workspace" },
  });
}

export function useMembers(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: [...keys.workspace(workspaceId), "members"],
    queryFn: () => api<Member[]>(`/api/v1/workspaces/${workspaceId}/members`),
    enabled,
  });
}

export function useChangeRole(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      api<Member>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, { method: "PATCH", body: { role } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.workspace(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.me });
    },
    meta: { success: "Role updated", error: "Could not change the role" },
  });
}

export function useRemoveMember(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      api<void>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.workspace(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.me });
    },
    meta: { success: "Member removed", error: "Could not remove the member" },
  });
}

export function useInvitations(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: [...keys.workspace(workspaceId), "invitations"],
    queryFn: () => api<Invitation[]>(`/api/v1/workspaces/${workspaceId}/invitations`),
    enabled,
  });
}

export function useInvite(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: Role }) =>
      api<InviteResult>(`/api/v1/workspaces/${workspaceId}/invitations`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.workspace(workspaceId) }),
  });
}

export function useRevokeInvitation(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) =>
      api<void>(`/api/v1/workspaces/${workspaceId}/invitations/${invitationId}`, { method: "DELETE" }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.workspace(workspaceId) }),
    meta: { success: "Invitation revoked", error: "Could not revoke the invitation" },
  });
}

export function useAdminSummary(enabled: boolean) {
  return useQuery({
    queryKey: [...keys.admin, "summary"],
    queryFn: () => api<{ pending_requests: number }>("/api/v1/admin/summary"),
    enabled,
    refetchInterval: 60_000,
  });
}

export function useAccessRequests(status: "pending" | "decided", enabled = true) {
  return useQuery({
    queryKey: [...keys.admin, "requests", status],
    queryFn: () => api<AccessRequest[]>(`/api/v1/admin/access-requests?status=${status}`),
    enabled,
  });
}

export type RequestDecision =
  | { id: string; decision: "approve"; workspaceId: string | null; role: Role }
  | { id: string; decision: "deny" };

type ApproveResult = { status: "approved"; workspace: "invited" | "added" | null };

export function useDecideRequest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: RequestDecision): Promise<ApproveResult | null> => {
      if (input.decision === "approve") {
        return api<ApproveResult>(`/api/v1/admin/access-requests/${input.id}/approve`, {
          method: "POST",
          body: { workspace_id: input.workspaceId, role: input.role },
        });
      }
      await api<void>(`/api/v1/admin/access-requests/${input.id}/deny`, { method: "POST" });
      return null;
    },
    onSettled: () => client.invalidateQueries({ queryKey: keys.admin }),
    meta: { error: "Could not record the decision" },
  });
}

export function useAccessList(enabled = true) {
  return useQuery({
    queryKey: [...keys.admin, "access-list"],
    queryFn: () => api<AccessEntry[]>("/api/v1/admin/access-list"),
    enabled,
  });
}

export function useAddAccess() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; note?: string }) =>
      api<AccessEntry>("/api/v1/admin/access-list", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.admin }),
    meta: { success: "Added to the access list" },
  });
}

export function useRemoveAccess() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) => api<void>(`/api/v1/admin/access-list/${entryId}`, { method: "DELETE" }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.admin }),
    meta: {
      success: "Access removed; that person was signed out everywhere",
      error: "Could not remove access",
    },
  });
}

export function useAdminWorkspaces(enabled = true) {
  return useQuery({
    queryKey: [...keys.admin, "workspaces"],
    queryFn: () => api<AdminWorkspace[]>("/api/v1/admin/workspaces"),
    enabled,
  });
}

export function useRuns(workspaceId: string) {
  return useQuery({
    queryKey: keys.runs(workspaceId),
    queryFn: () => api<RunSummary[]>(`/api/v1/runs?workspace_id=${encodeURIComponent(workspaceId)}`),
    refetchInterval: 10_000,
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: keys.run(runId),
    queryFn: () => api<RunDetail>(`/api/v1/runs/${runId}`),
  });
}

export function useEvidence(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.evidence(runId),
    queryFn: () => api<Evidence[]>(`/api/v1/runs/${runId}/evidence`),
    enabled,
  });
}

export function useSources(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["sources", runId],
    queryFn: () => api<Source[]>(`/api/v1/runs/${runId}/sources`),
    enabled,
  });
}

export function useUploads(workspaceId: string) {
  return useQuery({
    queryKey: ["uploads", workspaceId],
    queryFn: () => api<UploadInfo[]>(`/api/v1/workspaces/${workspaceId}/uploads`),
  });
}

export function useUploadSearch(workspaceId: string, query: string) {
  return useQuery({
    queryKey: ["upload-search", workspaceId, query],
    queryFn: () =>
      api<UploadSearchHit[]>(`/api/v1/workspaces/${workspaceId}/uploads/search?q=${encodeURIComponent(query)}`),
    enabled: query.trim().length >= 2,
  });
}

export function useStyleRewrite(workspaceId: string) {
  return useMutation({
    mutationFn: (input: StyleSourceInput & { persona: StylePersona }) =>
      api<StyleRewrite>(`/api/v1/workspaces/${workspaceId}/style/rewrite`, { method: "POST", body: input }),
    meta: { error: "Could not rewrite the text" },
  });
}

export function useUploadFile(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<UploadInfo>(`/api/v1/workspaces/${workspaceId}/uploads`, { method: "POST", form });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["uploads", workspaceId] }),
  });
}

export function useDeleteUpload(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (uploadId: string) =>
      api<void>(`/api/v1/workspaces/${workspaceId}/uploads/${uploadId}`, { method: "DELETE" }),
    onSettled: () => client.invalidateQueries({ queryKey: ["uploads", workspaceId] }),
    meta: { success: "Document deleted", error: "Could not delete the document" },
  });
}

export function useUsage(runId: string) {
  return useQuery({
    queryKey: ["usage", runId],
    queryFn: () => api<RunUsage>(`/api/v1/runs/${runId}/usage`),
  });
}

export function useWorkspaceUsage(workspaceId: string, days: number) {
  return useQuery({
    queryKey: ["workspace-usage", workspaceId, days],
    queryFn: () => api<WorkspaceUsage>(`/api/v1/workspaces/${workspaceId}/usage?days=${days}`),
  });
}

export function useReviews(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["reviews", runId],
    queryFn: () => api<ReviewRound[]>(`/api/v1/runs/${runId}/reviews`),
    enabled,
  });
}

export function useReportVersion(runId: string, version: number | null) {
  return useQuery({
    queryKey: ["report-version", runId, version],
    queryFn: () => api<Artifact<ReportBody>>(`/api/v1/reports/${runId}/versions/${version}`),
    enabled: version !== null,
    staleTime: Infinity, // versions are immutable
  });
}

export function useExports(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["exports", runId],
    queryFn: () => api<ExportRecord[]>(`/api/v1/runs/${runId}/exports`),
    enabled,
  });
}

export function useExportReport(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (version: number) => {
      const file = await download(`/api/v1/reports/${runId}/versions/${version}/export`);
      saveBlob(file.blob, file.filename);
      return file;
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["exports", runId] }),
    meta: { success: "Report downloaded" },
  });
}

export function useEditPlan(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ baseVersion, plan }: { baseVersion: number; plan: PlanBody }) =>
      api<Artifact<PlanBody>>(`/api/v1/runs/${runId}/plan`, { method: "PUT", body: { base_version: baseVersion, plan } }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.run(runId) }),
    meta: { success: "Plan saved as a new version" },
  });
}

export function useCreateRun(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ brief, idempotencyKey }: { brief: BriefInput; idempotencyKey: string }) =>
      api<RunDetail>("/api/v1/runs", {
        method: "POST",
        body: { workspace_id: workspaceId, brief },
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    onSuccess: (run) => {
      client.setQueryData(keys.run(run.id), run);
      void client.invalidateQueries({ queryKey: keys.runs(workspaceId) });
    },
    meta: { success: "Brief submitted; the planner is working on it" },
  });
}

export type DecisionInput = {
  kind: "plan" | "report";
  version: number;
  digest: string;
  decision: "approve" | "reject";
  comment?: string;
};

export function useDecide(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, ...body }: DecisionInput) =>
      api<Decision>(
        kind === "plan" ? `/api/v1/runs/${runId}/plan-decisions` : `/api/v1/reports/${runId}/decisions`,
        { method: "POST", body },
      ),
    onSettled: () => client.invalidateQueries({ queryKey: keys.run(runId) }),
    meta: { success: "Decision recorded" },
  });
}

export function useDeleteRun(runId: string, workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>(`/api/v1/runs/${runId}`, { method: "DELETE" }),
    onSuccess: () => {
      client.removeQueries({ queryKey: keys.run(runId) });
      void client.invalidateQueries({ queryKey: keys.runs(workspaceId) });
    },
    meta: { success: "Run deleted" },
  });
}

export function useAuditLog(workspaceId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["audit", workspaceId],
    queryFn: () => api<AuditEvent[]>(`/api/v1/workspaces/${workspaceId}/audit?limit=100`),
    enabled,
  });
}

/** Keeps the browser tab title meaningful for each page (screen readers announce it too). */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · Agent Orchestration` : "Agent Orchestration System";
  }, [title]);
}

export function useRunAction(runId: string, action: "cancel" | "retry") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<RunDetail>(`/api/v1/runs/${runId}/${action}`, { method: "POST" }),
    onSuccess: (run) => client.setQueryData(keys.run(runId), run),
    onError: () => client.invalidateQueries({ queryKey: keys.run(runId) }),
    meta: { success: action === "cancel" ? "Cancellation requested" : "Retry started" },
  });
}

export type StreamStatus = "connecting" | "live" | "reconnecting" | "ended";

const EVIDENCE_EVENTS = new Set(["source_collected", "source_failed", "task_completed"]);

/** Live run timeline over server-sent events. EventSource reconnects automatically and
 *  sends Last-Event-ID, so the server replays anything missed (FR-10). The stream of a
 *  finished run closes; bump `epoch` (e.g. after a retry) to subscribe again. */
export function useRunEvents(runId: string, epoch = 0): { events: RunEvent[]; status: StreamStatus } {
  const client = useQueryClient();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const seen = useRef(new Set<number>());

  useEffect(() => {
    seen.current = new Set();
    setEvents([]);
    setStatus("connecting");
    const source = new EventSource(`/api/v1/runs/${runId}/events`, { withCredentials: true });

    // Bursts of events (a worker pass emits many) trigger one coalesced refetch, not one each.
    const pending = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = (what: "run" | "evidence") => {
      pending.add(what);
      timer ??= setTimeout(() => {
        if (pending.has("run")) {
          void client.invalidateQueries({ queryKey: keys.run(runId) });
          void client.invalidateQueries({ queryKey: ["usage", runId] });
          void client.invalidateQueries({ queryKey: ["reviews", runId] });
        }
        if (pending.has("evidence")) {
          void client.invalidateQueries({ queryKey: keys.evidence(runId) });
          void client.invalidateQueries({ queryKey: ["sources", runId] });
        }
        pending.clear();
        timer = undefined;
      }, 250);
    };

    source.onopen = () => setStatus("live");
    source.onerror = () => setStatus(source.readyState === EventSource.CLOSED ? "ended" : "reconnecting");
    source.addEventListener("run_event", (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent;
      if (seen.current.has(event.id)) return;
      seen.current.add(event.id);
      setEvents((current) => [...current, event]);
      refresh(EVIDENCE_EVENTS.has(event.type) ? "evidence" : "run");
    });
    source.addEventListener("end", () => {
      source.close();
      setStatus("ended");
      refresh("run");
    });
    return () => {
      source.close();
      if (timer) clearTimeout(timer);
    };
  }, [runId, client, epoch]);

  return { events, status };
}

export function isTerminal(state: string): boolean {
  return TERMINAL_STATES.has(state as never);
}
