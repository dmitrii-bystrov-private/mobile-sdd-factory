import type {
  Artifact,
  EventItem,
  Role,
  Session,
  StreamEventPayload,
  WorkItem,
} from "../types";

const API_BASE =
  import.meta.env.VITE_SDD_FACTORY_API_BASE?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

const STREAM_EVENT_TYPES = [
  "task_started",
  "task_session_reused",
  "task_prepared",
  "task_preparation_failed",
  "implementation_requested",
  "implementation_completed",
  "verification_requested",
  "verification_failed",
  "verification_correction_requested",
  "verification_passed",
  "task_completed",
  "role_input_dispatched",
  "role_output_collected",
  "role_progress_reported",
  "role_runtime_error_reported",
  "session_output_polled",
  "session_paused_by_operator",
  "session_resumed_by_operator",
  "session_retried_by_operator",
  "session_redirected_by_operator",
  "session_escalated_to_operator",
  "session_dispatch_reconciled",
  "coordinator_loop_ran",
] as const;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export const apiClient = {
  listSessions(): Promise<{ items: Session[] }> {
    return request("/sessions");
  },

  listRoles(sessionId: number): Promise<{ items: Role[] }> {
    return request(`/roles?session_id=${sessionId}`);
  },

  listArtifacts(sessionId: number): Promise<{ items: Artifact[] }> {
    return request(`/artifacts?session_id=${sessionId}`);
  },

  listEvents(sessionId: number): Promise<{ items: EventItem[] }> {
    return request(`/events?session_id=${sessionId}`);
  },

  listWorkItems(sessionId: number): Promise<{ items: WorkItem[] }> {
    return request(`/work-items?session_id=${sessionId}`);
  },

  pauseSession(sessionId: number): Promise<{ event_type: string; session: Session }> {
    return request("/operator/pause-session", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  resumeSession(sessionId: number): Promise<{ event_type: string; session: Session }> {
    return request("/operator/resume-session", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  retrySession(sessionId: number): Promise<{ event_type: string; session: Session }> {
    return request("/operator/retry-session", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  redirectSession(
    sessionId: number,
    targetRoleName: string,
  ): Promise<{ event_type: string; session: Session }> {
    return request("/operator/redirect-session", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        target_role_name: targetRoleName,
      }),
    });
  },

  runLoopOnce(): Promise<{ event_type?: string | null; session_count: number; chunk_count: number }> {
    return request("/operator/run-loop-once", {
      method: "POST",
    });
  },
};

export function openSessionEventStream(
  sessionId: number,
  sinceEventId: number | null,
  onEvent: (eventType: string, payload: StreamEventPayload, lastEventId: number | null) => void,
  onError: () => void,
): () => void {
  const params = new URLSearchParams({
    session_id: String(sessionId),
  });
  if (sinceEventId !== null) {
    params.set("since_event_id", String(sinceEventId));
  }

  const eventSource = new EventSource(`${API_BASE}/events/stream?${params.toString()}`);

  for (const eventType of STREAM_EVENT_TYPES) {
    eventSource.addEventListener(eventType, (event) => {
      const message = event as MessageEvent<string>;
      const payload = JSON.parse(message.data) as StreamEventPayload;
      const parsedId =
        typeof message.lastEventId === "string" && message.lastEventId.length > 0
          ? Number(message.lastEventId)
          : null;
      onEvent(eventType, payload, Number.isFinite(parsedId) ? parsedId : null);
    });
  }

  eventSource.onerror = () => {
    onError();
  };

  return () => {
    eventSource.close();
  };
}
