import { startTransition, useEffect, useRef, useState } from "react";

import { apiClient, openSessionEventStream } from "../api/client";
import { EnvironmentDoctorPanel } from "../components/EnvironmentDoctorPanel";
import { BootstrapGuidancePanel } from "../components/BootstrapGuidancePanel";
import { RuntimeCapabilitiesPanel } from "../components/RuntimeCapabilitiesPanel";
import { RuntimeDefaultsPanel } from "../components/RuntimeDefaultsPanel";
import { SessionDetail } from "../components/SessionDetail";
import { KnowledgePanel } from "../components/KnowledgePanel";
import { SessionList } from "../components/SessionList";
import { SessionStartForm } from "../components/SessionStartForm";
import type {
  Artifact,
  ArtifactDetail,
  BootstrapGuidanceSummary,
  EnvironmentDoctorSummary,
  EventItem,
  FollowupContext,
  InteractiveStateSummary,
  JiraSubtasksSummary,
  KnowledgeItem,
  PlanningSummary,
  PlanningStepSummary,
  RuntimeCapabilitiesSummary,
  RuntimeDefaultsSummary,
  RuntimeSessionStateSummary,
  Session,
  SessionBundle,
  SubtaskGraphSummary,
  SubtaskProgressSummary,
} from "../types";

const FOLLOWUP_ARTIFACT_TYPES_BY_SOURCE: Record<"mr" | "qa", readonly string[]> = {
  mr: ["mr_followup_plan_markdown", "mr_comments_markdown"],
  qa: ["qa_reopen_comments"],
};
const FOLLOWUP_STAGE_EVENT_TYPES: Record<"mr" | "qa", readonly string[]> = {
  mr: [
    "mr_comments_analysis_requested",
    "subtask_graph_requested",
    "subtask_implementation_requested",
    "mr_followup_requested",
  ],
  qa: [
    "subtask_graph_requested",
    "subtask_implementation_requested",
    "qa_reopen_requested",
  ],
};
const PLANNING_STEP_DEFINITIONS = [
  {
    stageName: "proposal_context_requested",
    label: "Proposal & Context",
    completedEventType: "proposal_context_completed",
  },
  {
    stageName: "requirements_requested",
    label: "Requirements",
    completedEventType: "requirements_completed",
  },
  {
    stageName: "acceptance_criteria_requested",
    label: "Acceptance Criteria",
    completedEventType: "acceptance_criteria_completed",
  },
  {
    stageName: "constraints_requested",
    label: "Constraints",
    completedEventType: "constraints_completed",
  },
  {
    stageName: "spec_verification_requested",
    label: "Spec Verification",
    completedEventType: "spec_verification_completed",
  },
  {
    stageName: "story_spec_requested",
    label: "Story Spec",
    completedEventType: "story_spec_completed",
  },
  {
    stageName: "task_decomposition_requested",
    label: "Task Decomposition",
    completedEventType: "task_decomposition_completed",
  },
] as const;

function latestPlanningArtifactForStage(
  artifacts: Artifact[],
  stageName: string,
): Artifact | null {
  if (stageName === "task_decomposition_requested") {
    const decompositionArtifact = [...artifacts]
      .reverse()
      .find((artifact) => artifact.artifact_type === "task_decomposition_markdown");
    if (decompositionArtifact !== undefined) {
      return decompositionArtifact;
    }
  }

  const roleSummaryArtifact = [...artifacts]
    .reverse()
    .find(
      (artifact) =>
        artifact.artifact_type === "role_output_summary" &&
        artifact.metadata?.current_stage === stageName,
    );
  return roleSummaryArtifact ?? null;
}

async function buildPlanningSummary(
  artifacts: Artifact[],
  events: EventItem[],
): Promise<PlanningSummary | null> {
  const hasPlanningSignal = events.some((event) =>
    PLANNING_STEP_DEFINITIONS.some(
      (step) => event.event_type === step.stageName || event.event_type === step.completedEventType,
    ),
  );

  if (!hasPlanningSignal) {
    return null;
  }

  const artifactsByStage = new Map<string, Artifact | null>();
  for (const step of PLANNING_STEP_DEFINITIONS) {
    artifactsByStage.set(step.stageName, latestPlanningArtifactForStage(artifacts, step.stageName));
  }

  const artifactDetailsById = new Map<number, ArtifactDetail>();
  await Promise.all(
    [...artifactsByStage.values()]
      .filter((artifact): artifact is Artifact => artifact !== null)
      .map(async (artifact) => {
        if (!artifactDetailsById.has(artifact.id)) {
          artifactDetailsById.set(artifact.id, await apiClient.getArtifact(artifact.id));
        }
      }),
  );

  const steps: PlanningStepSummary[] = PLANNING_STEP_DEFINITIONS.map((step) => {
    const artifact = artifactsByStage.get(step.stageName) ?? null;
    const artifactDetail = artifact !== null ? artifactDetailsById.get(artifact.id) ?? null : null;
    const completed = events.some((event) => event.event_type === step.completedEventType);
    const active = !completed && events.some((event) => event.event_type === step.stageName);

    return {
      stageName: step.stageName,
      label: step.label,
      status: completed ? "completed" : active ? "active" : "pending",
      artifactType: artifact?.artifact_type ?? null,
      artifactDetail,
    };
  });

  const currentStep = [...steps].reverse().find((step) => step.status === "active") ?? null;

  return {
    stageCount: steps.length,
    completedCount: steps.filter((step) => step.status === "completed").length,
    currentStage: currentStep?.stageName ?? null,
    steps,
  };
}

async function buildJiraSubtasksSummary(
  sessionId: number,
): Promise<JiraSubtasksSummary | null> {
  const response = await apiClient.getJiraSubtasks(sessionId);
  if (!response.available || response.total_count === 0) {
    return null;
  }
  return {
    available: response.available,
    totalCount: response.total_count,
    items: response.items.map((item) => ({
      key: item.key,
      title: item.title,
      status: item.status,
      queuePosition: item.queue_position,
      isCurrent: item.is_current,
    })),
  };
}

async function buildInteractiveStateSummary(
  sessionId: number,
): Promise<InteractiveStateSummary | null> {
  const response = await apiClient.getInteractiveState(sessionId);
  if (!response.available) {
    return null;
  }
  return {
    available: response.available,
    roleName: response.role_name,
    currentStage: response.current_stage,
    summary: response.summary,
    details: response.details,
    sourceEventType: response.source_event_type,
    sourceReason: response.source_reason,
    needsOperatorInput: response.needs_operator_input,
  };
}

async function buildRuntimeStateSummary(
  sessionId: number,
): Promise<RuntimeSessionStateSummary | null> {
  const response = await apiClient.getRuntimeState(sessionId);
  if (!response.available) {
    return null;
  }
  return {
    available: response.available,
    runtimeSessionId: response.runtime_session_id,
    tmuxSocketPath: response.tmux_socket_path,
    tmuxAttachCommand: response.tmux_attach_command,
    lastAutoRecovery: response.last_auto_recovery
      ? {
          roleName: response.last_auto_recovery.role_name,
          currentStage: response.last_auto_recovery.current_stage,
          runtimeHandle: response.last_auto_recovery.runtime_handle,
          deadRuntimeHandle: response.last_auto_recovery.dead_runtime_handle,
          eventId: response.last_auto_recovery.event_id,
          createdAt: response.last_auto_recovery.created_at,
        }
      : null,
    roles: response.roles.map((role) => ({
      roleName: role.role_name,
      status: role.status,
      runtimeBackend: role.runtime_backend,
      runtimeHandle: role.runtime_handle,
      tmuxAttachCommand: role.tmux_attach_command,
      tmuxCaptureCommand: role.tmux_capture_command,
    })),
  };
}

async function buildSubtaskGraphSummary(
  sessionId: number,
): Promise<SubtaskGraphSummary | null> {
  const response = await apiClient.getSubtaskGraph(sessionId);
  if (!response.available || response.total_count === 0) {
    return null;
  }
  return {
    available: response.available,
    totalCount: response.total_count,
    completedCount: response.completed_count,
    unresolvedCount: response.unresolved_count,
    rows: response.rows.map((row) => ({
      key: row.key,
      issueType: row.issue_type,
      title: row.title,
      status: row.status,
    })),
  };
}

async function buildSubtaskProgressSummary(
  sessionId: number,
): Promise<SubtaskProgressSummary | null> {
  const response = await apiClient.getSubtaskProgress(sessionId);
  if (!response.available || response.total_count === 0) {
    return null;
  }
  return {
    available: response.available,
    currentSubtaskKey: response.current_subtask_key,
    currentSubtaskTitle: response.current_subtask_title,
    totalCount: response.total_count,
    completedCount: response.completed_count,
    remainingCount: response.remaining_count,
    items: response.items.map((item) => ({
      workItemId: item.work_item_id,
      key: item.key,
      title: item.title,
      status: item.status,
      queuePosition: item.queue_position,
    })),
  };
}

function buildFollowupContext(
  artifacts: Artifact[],
  events: EventItem[],
): Promise<FollowupContext | null> | FollowupContext | null {
  const sourceEvent = [...events]
    .reverse()
    .find((event) => event.event_type === "mr_comments_received" || event.event_type === "qa_reopened");
  if (sourceEvent === undefined) {
    return null;
  }

  const source =
    sourceEvent.event_type === "mr_comments_received" ? "mr" : "qa";
  const followupEvent = events.find(
    (event) =>
      event.id > sourceEvent.id &&
      FOLLOWUP_STAGE_EVENT_TYPES[source].includes(event.event_type),
  );
  const followupArtifact = FOLLOWUP_ARTIFACT_TYPES_BY_SOURCE[source]
    .map((artifactType) =>
      [...artifacts]
        .reverse()
        .find((artifact) => artifact.artifact_type === artifactType),
    )
    .find((artifact): artifact is Artifact => artifact !== undefined);

  if (followupArtifact === undefined) {
    return {
      source,
      eventId: sourceEvent.id,
      eventType: sourceEvent.event_type,
      stageName: followupEvent?.event_type ?? "followup_implementation",
      artifactType: "missing_followup_artifact",
      artifactDetail: null,
      eventPayload: sourceEvent.payload,
    };
  }

  return apiClient.getArtifact(followupArtifact.id).then((artifactDetail) => ({
    source,
    eventId: sourceEvent.id,
    eventType: sourceEvent.event_type,
    stageName: followupEvent?.event_type ?? followupArtifact.stage_name,
    artifactType: followupArtifact.artifact_type,
    artifactDetail,
    eventPayload: sourceEvent.payload,
  }));
}

export function SessionsPage(): JSX.Element {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [bundle, setBundle] = useState<SessionBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [doctorSummary, setDoctorSummary] = useState<EnvironmentDoctorSummary | null>(null);
  const [bootstrapGuidanceSummary, setBootstrapGuidanceSummary] =
    useState<BootstrapGuidanceSummary | null>(null);
  const [runtimeCapabilitiesSummary, setRuntimeCapabilitiesSummary] =
    useState<RuntimeCapabilitiesSummary | null>(null);
  const [runtimeDefaultsSummary, setRuntimeDefaultsSummary] =
    useState<RuntimeDefaultsSummary | null>(null);
  const [streamState, setStreamState] = useState<"idle" | "live" | "reconnecting">("idle");
  const [lastStreamEventType, setLastStreamEventType] = useState<string | null>(null);
  const [lastStreamEventId, setLastStreamEventId] = useState<number | null>(null);
  const refreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const selectedSession =
    sessions.find((session) => session.id === selectedSessionId) ?? null;

  async function loadSessions(): Promise<number | null> {
    setLoading(true);
    setError(null);
    try {
      const sessionResponse = await apiClient.listSessions();
      const knowledgeResponse = await apiClient.listKnowledge();
      const doctorResponse = await apiClient.getEnvironmentDoctor();
      const guidanceResponse = await apiClient.getBootstrapGuidance();
      const runtimeCapabilitiesResponse = await apiClient.getRuntimeCapabilities();
      const runtimeDefaultsResponse = await apiClient.getRuntimeDefaults();
      setSessions(sessionResponse.items);
      setKnowledgeItems(knowledgeResponse.items);
      setDoctorSummary({
        overallStatus: doctorResponse.overall_status,
        repoRoot: doctorResponse.repo_root,
        requiredOk: doctorResponse.required_ok,
        requiredTotal: doctorResponse.required_total,
        optionalWarnings: doctorResponse.optional_warnings,
        checks: doctorResponse.checks.map((check) => ({
          id: check.id,
          category: check.category,
          label: check.label,
          required: check.required,
          status: check.status,
          details: check.details,
          value: check.value,
          source: check.source,
          hint: check.hint,
        })),
      });
      setBootstrapGuidanceSummary({
        overallStatus: guidanceResponse.overall_status,
        requiredActionCount: guidanceResponse.required_action_count,
        optionalActionCount: guidanceResponse.optional_action_count,
        nextStep: guidanceResponse.next_step,
        launchCommand: guidanceResponse.launch_command,
        backendUrl: guidanceResponse.backend_url,
        uiUrl: guidanceResponse.ui_url,
        requiredActions: guidanceResponse.required_actions.map((item) => ({
          id: item.id,
          label: item.label,
          status: item.status,
          details: item.details,
          hint: item.hint,
        })),
        optionalActions: guidanceResponse.optional_actions.map((item) => ({
          id: item.id,
          label: item.label,
          status: item.status,
          details: item.details,
          hint: item.hint,
        })),
      });
      setRuntimeCapabilitiesSummary({
        availableRunners: runtimeCapabilitiesResponse.available_runners,
        defaultRunner: runtimeCapabilitiesResponse.default_runner,
        runners: runtimeCapabilitiesResponse.runners.map((runner) => ({
          runner: runner.runner,
          available: runner.available,
          source: runner.source,
          path: runner.path,
          supportsCustomModel: runner.supports_custom_model,
          models: runner.models.map((model) => ({
            id: model.id,
            label: model.label,
            supportedEfforts: model.supported_efforts,
            defaultEffort: model.default_effort,
            visibility: model.visibility,
            supportedInApi: model.supported_in_api,
            source: model.source,
          })),
        })),
        roleDefaults: runtimeCapabilitiesResponse.role_defaults.map((item) => ({
          roleName: item.role_name,
          model: item.model,
          effort: item.effort,
          mcpServers: item.mcp_servers,
          source: item.source,
        })),
      });
      setRuntimeDefaultsSummary({
        defaultRunner: runtimeDefaultsResponse.default_runner,
        roleDefaults: runtimeDefaultsResponse.role_defaults,
        policyDefaults: runtimeDefaultsResponse.policy_defaults,
        knownRoles: runtimeDefaultsResponse.known_roles,
        sourcePath: runtimeDefaultsResponse.source_path,
      });
      const availableIds = new Set(sessionResponse.items.map((session) => session.id));
      const nextSelectedId =
        selectedSessionId !== null && availableIds.has(selectedSessionId)
          ? selectedSessionId
          : sessionResponse.items[0]?.id ?? null;
      startTransition(() => {
        setSelectedSessionId(nextSelectedId);
      });
      return nextSelectedId;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function loadBundle(sessionId: number): Promise<void> {
    setError(null);
    try {
      const [roles, artifacts, events, workItems] = await Promise.all([
        apiClient.listRoles(sessionId),
        apiClient.listArtifacts(sessionId),
        apiClient.listEvents(sessionId),
        apiClient.listWorkItems(sessionId),
      ]);
      const [
        followupContext,
        planningSummary,
        interactiveStateSummary,
        runtimeStateSummary,
        jiraSubtasksSummary,
        subtaskGraphSummary,
        subtaskProgressSummary,
      ] = await Promise.all([
        Promise.resolve(buildFollowupContext(artifacts.items, events.items)),
        buildPlanningSummary(artifacts.items, events.items),
        buildInteractiveStateSummary(sessionId),
        buildRuntimeStateSummary(sessionId),
        buildJiraSubtasksSummary(sessionId),
        buildSubtaskGraphSummary(sessionId),
        buildSubtaskProgressSummary(sessionId),
      ]);
      setBundle({
        roles: roles.items,
        artifacts: artifacts.items,
        events: events.items,
        workItems: workItems.items,
        followupContext,
        planningSummary,
        interactiveStateSummary,
        runtimeStateSummary,
        jiraSubtasksSummary,
        subtaskGraphSummary,
        subtaskProgressSummary,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session detail");
    }
  }

  async function refreshSelected(): Promise<void> {
    const nextSelectedId = await loadSessions();
    if (nextSelectedId !== null) {
      await loadBundle(nextSelectedId);
    } else {
      setBundle(null);
    }
  }

  function scheduleLiveRefresh(): void {
    if (selectedSessionId === null) {
      return;
    }
    if (refreshTimeoutRef.current !== null) {
      return;
    }
    refreshTimeoutRef.current = setTimeout(() => {
      refreshTimeoutRef.current = null;
      void refreshSelected();
    }, 180);
  }

  useEffect(() => {
    void loadSessions();
  }, []);

  useEffect(() => {
    if (selectedSessionId === null) {
      setBundle(null);
      return;
    }
    void loadBundle(selectedSessionId);
  }, [selectedSessionId]);

  useEffect(() => {
    if (selectedSessionId === null) {
      setStreamState("idle");
      setLastStreamEventType(null);
      return;
    }

    const latestKnownEventId =
      bundle !== null && bundle.events.length > 0
        ? bundle.events[bundle.events.length - 1].id
        : null;
    const close = openSessionEventStream(
      selectedSessionId,
      latestKnownEventId,
      (eventType, _payload, incomingEventId) => {
        setStreamState("live");
        setLastStreamEventType(eventType);
        if (incomingEventId !== null) {
          setLastStreamEventId(incomingEventId);
        }
        scheduleLiveRefresh();
      },
      () => {
        setStreamState("reconnecting");
      },
    );

    return () => {
      close();
    };
  }, [selectedSessionId, bundle?.events]);

  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current !== null) {
        clearTimeout(refreshTimeoutRef.current);
      }
    };
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">SDD Factory</p>
          <h1>Operator Console</h1>
        </div>
        <div className="topbar-actions">
          <div className={`live-chip live-${streamState}`}>
            <span className="live-dot" />
            <strong>{streamState}</strong>
            <small>
              {lastStreamEventType
                ? `${lastStreamEventType}${lastStreamEventId !== null ? ` #${lastStreamEventId}` : ""}`
                : "waiting for events"}
            </small>
          </div>
          <button
            className="action-button action-button-strong"
            onClick={() => void refreshSelected()}
            title="Reload the session list and the currently selected session surface."
            type="button"
          >
            Refresh Surface
          </button>
        </div>
      </header>

      {error ? <div className="error-banner top-error">{error}</div> : null}

      <div className="page-layout">
        <div className="sidebar-stack">
          <SessionStartForm
            onCreated={async (sessionId) => {
              await loadSessions();
              setSelectedSessionId(sessionId);
              await loadBundle(sessionId);
            }}
            runtimeCapabilities={runtimeCapabilitiesSummary}
            runtimeDefaults={runtimeDefaultsSummary}
          />
          <RuntimeDefaultsPanel
            onSaved={(summary) => {
              setRuntimeDefaultsSummary(summary);
            }}
            runtimeCapabilities={runtimeCapabilitiesSummary}
            runtimeDefaults={runtimeDefaultsSummary}
          />
          <SessionList
            onSelect={(sessionId) => setSelectedSessionId(sessionId)}
            selectedSessionId={selectedSessionId}
            sessions={sessions}
          />
          <EnvironmentDoctorPanel doctorSummary={doctorSummary} />
          <BootstrapGuidancePanel guidanceSummary={bootstrapGuidanceSummary} />
          <RuntimeCapabilitiesPanel capabilities={runtimeCapabilitiesSummary} />
          <KnowledgePanel items={knowledgeItems} />
        </div>
        {loading ? (
          <section className="panel panel-empty">
            <p className="eyebrow">Loading</p>
            <h2>Hydrating operator surface…</h2>
          </section>
        ) : (
          <SessionDetail
            bundle={bundle}
            onRefresh={refreshSelected}
            session={selectedSession}
          />
        )}
      </div>
    </main>
  );
}
