import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, download, saveBlob, setCsrfToken } from "./client";
import type {
  Artifact,
  BriefInput,
  Decision,
  Evidence,
  ExportRecord,
  Me,
  PlanBody,
  ReportBody,
  ReviewRound,
  RunDetail,
  RunEvent,
  RunSummary,
  RunUsage,
  Source,
  UploadInfo,
  UploadSearchHit,
} from "./types";
import { TERMINAL_STATES } from "./types";

export const keys = {
  me: ["me"] as const,
  runs: (workspaceId: string) => ["runs", workspaceId] as const,
  run: (runId: string) => ["run", runId] as const,
  evidence: (runId: string) => ["evidence", runId] as const,
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

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
    onSettled: () => {
      setCsrfToken(null);
      client.clear();
      window.location.assign("/signin");
    },
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
  });
}

export function useUsage(runId: string) {
  return useQuery({
    queryKey: ["usage", runId],
    queryFn: () => api<RunUsage>(`/api/v1/runs/${runId}/usage`),
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
  });
}

export function useEditPlan(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ baseVersion, plan }: { baseVersion: number; plan: PlanBody }) =>
      api<Artifact<PlanBody>>(`/api/v1/runs/${runId}/plan`, { method: "PUT", body: { base_version: baseVersion, plan } }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.run(runId) }),
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
  });
}

export type StreamStatus = "connecting" | "live" | "reconnecting" | "ended";

const EVIDENCE_EVENTS = new Set(["source_collected", "source_failed", "task_completed"]);

/** Live run timeline over server-sent events. EventSource reconnects automatically and
 *  sends Last-Event-ID, so the server replays anything missed (FR-10). */
export function useRunEvents(runId: string): { events: RunEvent[]; status: StreamStatus } {
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
  }, [runId, client]);

  return { events, status };
}

export function isTerminal(state: string): boolean {
  return TERMINAL_STATES.has(state as never);
}
