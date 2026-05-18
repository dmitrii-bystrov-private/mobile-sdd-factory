import type {
  Artifact,
  ArtifactDetail,
  EventItem,
  KnowledgeItem,
  RequirementsClarificationMode,
  Role,
  RuntimeDefaultsSummary,
  SessionPolicyEntry,
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
  "snapshot_refreshed_by_operator",
  "snapshot_refresh_failed_by_operator",
  "snapshot_continue_processed",
  "subtask_state_refreshed_by_operator",
  "subtask_state_refresh_failed_by_operator",
  "subtask_graph_requested",
  "subtask_implementation_requested",
  "subtask_completed",
  "knowledge_created",
  "implementation_requested",
  "implementation_completed",
  "self_review_requested",
  "self_review_passed",
  "self_review_issues_found",
  "boy_scout_requested",
  "boy_scout_completed",
  "boy_scout_skipped_by_operator",
  "boy_scout_implement_now_selected",
  "boy_scout_tech_debt_created",
  "boy_scout_correction_requested",
  "self_review_correction_requested",
  "doc_harvest_requested",
  "doc_harvest_completed",
  "spec_verification_blocked",
  "subtask_creation_requested",
  "verification_requested",
  "verification_failed",
  "verification_correction_requested",
  "verification_passed",
  "task_completed",
  "mr_comments_empty",
  "mr_comments_received",
  "mr_comments_analysis_requested",
  "mr_comments_analysis_completed",
  "proposal_external_links_detected",
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
  "runtime_role_restarted_by_operator",
  "runtime_session_restarted_by_operator",
  "operator_runtime_input_sent",
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
    requirements_clarification_mode?: RequirementsClarificationMode;
  };
  role_config?: Record<string, { runner: string; model: string; effort: string }>;
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

  getSubtaskGraph(sessionId: number): Promise<{
    available: boolean;
    total_count: number;
    completed_count: number;
    unresolved_count: number;
    rows: Array<{ key: string; issue_type: string; title: string; status: string }>;
  }> {
    return request(`/sessions/${sessionId}/subtask-graph`);
  },

  getSubtaskProgress(sessionId: number): Promise<{
    available: boolean;
    current_subtask_key: string | null;
    current_subtask_title: string | null;
    total_count: number;
    completed_count: number;
    remaining_count: number;
    items: Array<{
      work_item_id: number;
      key: string | null;
      title: string;
      status: string;
      queue_position: number;
    }>;
  }> {
    return request(`/sessions/${sessionId}/subtask-progress`);
  },

  getJiraSubtasks(sessionId: number): Promise<{
    available: boolean;
    total_count: number;
    items: Array<{
      key: string;
      title: string | null;
      status: string | null;
      queue_position: number | null;
      is_current: boolean;
    }>;
  }> {
    return request(`/sessions/${sessionId}/jira-subtasks`);
  },

  getInteractiveState(sessionId: number): Promise<{
    available: boolean;
    role_name: string | null;
    current_stage: string | null;
    summary: string | null;
    details: string | null;
    source_event_type: string | null;
    needs_operator_input: boolean;
  }> {
    return request(`/sessions/${sessionId}/interactive-state`);
  },

  getRuntimeState(sessionId: number): Promise<{
    available: boolean;
    runtime_session_id: string | null;
    tmux_socket_path: string | null;
    tmux_attach_command: string | null;
    last_auto_recovery: {
      role_name: string | null;
      current_stage: string | null;
      runtime_handle: string | null;
      dead_runtime_handle: string | null;
      event_id: number;
      created_at: string;
    } | null;
    roles: Array<{
      role_name: string;
      status: string;
      runtime_backend: string;
      runtime_handle: string | null;
      tmux_attach_command: string | null;
      tmux_capture_command: string | null;
    }>;
  }> {
    return request(`/sessions/${sessionId}/runtime-state`);
  },

  getEnvironmentDoctor(): Promise<{
    overall_status: string;
    repo_root: string;
    required_ok: number;
    required_total: number;
    optional_warnings: number;
    checks: Array<{
      id: string;
      category: string;
      label: string;
      required: boolean;
      status: string;
      details: string;
      value: string | null;
      source: string | null;
      hint: string | null;
    }>;
  }> {
    return request("/operator/environment-doctor");
  },

  getBootstrapGuidance(): Promise<{
    overall_status: string;
    required_action_count: number;
    optional_action_count: number;
    next_step: string;
    launch_command: string;
    backend_url: string;
    ui_url: string;
    required_actions: Array<{
      id: string;
      label: string;
      status: string;
      details: string;
      hint: string | null;
    }>;
    optional_actions: Array<{
      id: string;
      label: string;
      status: string;
      details: string;
      hint: string | null;
    }>;
  }> {
    return request("/operator/bootstrap-guidance");
  },

  getRuntimeCapabilities(): Promise<{
    available_runners: string[];
    default_runner: string | null;
    runners: Array<{
      runner: string;
      available: boolean;
      source: string;
      path: string | null;
      supports_custom_model: boolean;
      models: Array<{
        id: string;
        label: string;
        supported_efforts: string[];
        default_effort: string | null;
        visibility: string;
        supported_in_api: boolean;
        source: string;
      }>;
    }>;
    legacy_role_defaults: Array<{
      role_name: string;
      model: string | null;
      effort: string | null;
      mcp_servers: string[];
      source: string;
    }>;
  }> {
    return request("/operator/runtime-capabilities");
  },

  getRuntimeDefaults(): Promise<{
    default_runner: string | null;
    role_defaults: Record<string, { runner: string | null; model: string | null; effort: string | null }>;
    policy_defaults: Record<string, Record<string, SessionPolicyEntry>>;
    known_roles: string[];
    source_path: string;
  }> {
    return request("/operator/runtime-defaults");
  },

  updateRuntimeDefaults(payload: RuntimeDefaultsSummary): Promise<{
    default_runner: string | null;
    role_defaults: Record<string, { runner: string | null; model: string | null; effort: string | null }>;
    policy_defaults: Record<string, Record<string, SessionPolicyEntry>>;
    known_roles: string[];
    source_path: string;
  }> {
    return request("/operator/runtime-defaults", {
      method: "POST",
      body: JSON.stringify({
        default_runner: payload.defaultRunner,
        role_defaults: payload.roleDefaults,
        policy_defaults: payload.policyDefaults,
      }),
    });
  },

  listKnowledge(): Promise<{ items: KnowledgeItem[] }> {
    return request("/knowledge");
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

  stopRuntimeRole(
    sessionId: number,
    roleName: string,
  ): Promise<{ event_type: string; session: Session }> {
    return request("/operator/stop-runtime-role", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, role_name: roleName }),
    });
  },

  restartRuntimeRole(
    sessionId: number,
    roleName: string,
  ): Promise<{ event_type: string; followup_event_type: string | null; session: Session }> {
    return request("/operator/restart-runtime-role", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, role_name: roleName }),
    });
  },

  stopRuntimeSession(sessionId: number): Promise<{ event_type: string; session: Session }> {
    return request("/operator/stop-runtime-session", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  restartRuntimeSession(
    sessionId: number,
  ): Promise<{ event_type: string; followup_event_type: string | null; session: Session }> {
    return request("/operator/restart-runtime-session", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  cleanupTask(
    sessionId: number,
    cleanupMode: "soft" | "full",
    force = false,
  ): Promise<{
    cleaned: boolean;
    deleted_session: boolean;
    cleanup_mode: string;
    task_key: string;
    jira_status: string | null;
    full_cleanup_allowed: boolean;
    removed_paths: string[];
    session: Session | null;
  }> {
    return request("/operator/cleanup-task", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        cleanup_mode: cleanupMode,
        force,
      }),
    });
  },

  sendRuntimeInput(
    sessionId: number,
    text: string,
  ): Promise<{ event_type: string; session: Session }> {
    return request("/operator/send-runtime-input", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, text }),
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

  skipBoyScout(
    sessionId: number,
    reason: string,
  ): Promise<{
    skipped: boolean;
    event_type: string;
    followup_event_type: string | null;
    session: Session;
  }> {
    return request("/operator/skip-boy-scout", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        reason,
      }),
    });
  },

  resolveBoyScoutFindings(
    sessionId: number,
    resolution: "implement_now" | "create_tech_debt",
  ): Promise<{
    resolved: boolean;
    event_type: string;
    followup_event_type: string | null;
    session: Session;
  }> {
    return request("/operator/resolve-boy-scout-findings", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        resolution,
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

  createSubtasksFromPlan(
    sessionId: number,
  ): Promise<{
    created: boolean;
    event_type: string;
    followup_event_type?: string | null;
    session: Session;
  }> {
    return request("/operator/create-subtasks-from-plan", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
      }),
    });
  },

  refreshSubtaskState(
    sessionId: number,
  ): Promise<{
    refreshed: boolean;
    event_type: string;
    followup_event_type?: string | null;
    session: Session;
  }> {
    return request("/operator/refresh-subtask-state", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
      }),
    });
  },

  refreshSnapshot(
    sessionId: number,
  ): Promise<{
    refreshed: boolean;
    event_type: string;
    followup_event_type?: string | null;
    session: Session;
  }> {
    return request("/operator/refresh-snapshot", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
      }),
    });
  },

  createKnowledge(
    sessionId: number,
    title: string,
    guidance: string,
    scope: string,
  ): Promise<{
    created: boolean;
    event_type: string;
    session: Session;
  }> {
    return request("/operator/create-knowledge", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        title,
        guidance,
        scope: scope || null,
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
