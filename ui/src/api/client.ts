import type {
  Artifact,
  ArtifactDetail,
  EventItem,
  Role,
  SessionPolicyValue,
  Session,
  StreamEventPayload,
  WorkflowProfile,
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
  "bug_analysis_requested",
  "bug_analysis_completed",
  "story_spec_requested",
  "story_spec_completed",
  "subtask_graph_requested",
  "subtask_implementation_requested",
  "subtask_completed",
  "implementation_requested",
  "implementation_completed",
  "self_review_requested",
  "self_review_passed",
  "self_review_issues_found",
  "self_review_correction_requested",
  "doc_harvest_requested",
  "doc_harvest_completed",
  "verification_requested",
  "verification_failed",
  "verification_correction_requested",
  "verification_passed",
  "task_completed",
  "mr_comments_empty",
  "mr_comments_received",
  "mr_followup_requested",
  "mr_handoff_completed",
  "mr_handoff_failed",
  "send_to_test_completed",
  "send_to_test_failed",
  "qa_reopened",
  "qa_reopen_requested",
  "role_input_dispatched",
  "role_output_collected",
  "role_progress_reported",
  "role_runtime_error_reported",
  "session_output_polled",
  "session_paused_by_operator",
  "session_resumed_by_operator",
  "session_retried_by_operator",
  "session_escalated_to_operator",
  "session_dispatch_reconciled",
  "coordinator_loop_ran",
] as const;

type CreateSessionPayload = {
  task_key: string;
  workflow_profile: WorkflowProfile;
  policy: {
    self_review_policy: SessionPolicyValue;
    boy_scout_policy: SessionPolicyValue;
    doc_harvest_policy: SessionPolicyValue;
    test_policy?: SessionPolicyValue;
  };
};

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
  createSession(
    payload: CreateSessionPayload,
  ): Promise<{ created: boolean; event_type: string; session: Session }> {
    return request("/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  prepareSession(taskKey: string): Promise<{ created: boolean; event_type: string; session: Session }> {
    return request("/sessions/prepare", {
      method: "POST",
      body: JSON.stringify({ task_key: taskKey }),
    });
  },

  listSessions(): Promise<{ items: Session[] }> {
    return request("/sessions");
  },

  listRoles(sessionId: number): Promise<{ items: Role[] }> {
    return request(`/roles?session_id=${sessionId}`);
  },

  listArtifacts(sessionId: number): Promise<{ items: Artifact[] }> {
    return request(`/artifacts?session_id=${sessionId}`);
  },

  getArtifact(artifactId: number): Promise<ArtifactDetail> {
    return request(`/artifacts/${artifactId}`);
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

  ingestMrComments(
    sessionId: number,
    platform: "ios" | "android",
    mrId: string,
  ): Promise<{
    ingested: boolean;
    event_type: string;
    followup_event_type: string | null;
    discussion_count: number;
    session: Session;
  }> {
    return request("/operator/ingest-mr-comments", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        platform,
        mr_id: mrId,
      }),
    });
  },

  reopenFromQa(
    sessionId: number,
    commentText: string,
  ): Promise<{
    reopened: boolean;
    event_type: string;
    followup_event_type: string | null;
    session: Session;
  }> {
    return request("/operator/reopen-from-qa", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        comment_text: commentText,
      }),
    });
  },

  createMr(
    sessionId: number,
  ): Promise<{
    handed_off: boolean;
    event_type: string;
    mr_url: string | null;
    session: Session;
  }> {
    return request("/operator/create-mr", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
      }),
    });
  },

  completeDocHarvest(
    sessionId: number,
    summary: string,
  ): Promise<{
    completed: boolean;
    event_type: string;
    session: Session;
  }> {
    return request("/operator/complete-doc-harvest", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        summary,
      }),
    });
  },

  completeSelfReview(
    sessionId: number,
    outcome: "passed" | "issues_found",
    summary: string,
  ): Promise<{
    completed: boolean;
    event_type: string;
    followup_event_type: string | null;
    session: Session;
  }> {
    return request("/operator/complete-self-review", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        outcome,
        summary,
      }),
    });
  },

  sendToTest(
    sessionId: number,
  ): Promise<{
    handed_off: boolean;
    event_type: string;
    session: Session;
  }> {
    return request("/operator/send-to-test", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
      }),
    });
  },

  startSubtaskGraph(
    sessionId: number,
  ): Promise<{
    started: boolean;
    event_type: string;
    followup_event_type: string;
    session: Session;
  }> {
    return request("/operator/start-subtask-graph", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
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
