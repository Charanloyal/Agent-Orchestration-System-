import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, setCsrfToken } from "./client";
import type { BriefInput, Decision, Evidence, Me, RunDetail, RunEvent, RunSummary } from "./types";
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
        if (pending.has("run")) void client.invalidateQueries({ queryKey: keys.run(runId) });
        if (pending.has("evidence")) void client.invalidateQueries({ queryKey: keys.evidence(runId) });
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
      refresh(event.type === "source_collected" || event.type === "task_completed" ? "evidence" : "run");
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
