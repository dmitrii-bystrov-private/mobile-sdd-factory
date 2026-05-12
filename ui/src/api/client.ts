import type { Artifact, EventItem, Role, Session, WorkItem } from "../types";

const API_BASE =
  import.meta.env.VITE_SDD_FACTORY_API_BASE?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

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
