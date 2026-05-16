import { startTransition, useEffect, useRef, useState } from "react";

import { apiClient, openSessionEventStream } from "../api/client";
import { SessionDetail } from "../components/SessionDetail";
import { KnowledgePanel } from "../components/KnowledgePanel";
import { SessionList } from "../components/SessionList";
import { SessionStartForm } from "../components/SessionStartForm";
import type {
  Artifact,
  ArtifactDetail,
  EventItem,
  FollowupContext,
  JiraSubtasksSummary,
  KnowledgeItem,
  PlanningSummary,
  PlanningStepSummary,
  Session,
  SessionBundle,
  SubtaskGraphSummary,
  SubtaskProgressSummary,
} from "../types";

const FOLLOWUP_ARTIFACT_TYPES = new Set(["mr_comments_markdown", "qa_reopen_comments"]);
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
  const expectedFollowupEventType =
    source === "mr" ? "mr_followup_requested" : "qa_reopen_requested";
  const followupEvent = events.find(
    (event) => event.id > sourceEvent.id && event.event_type === expectedFollowupEventType,
  );
  const followupArtifact = [...artifacts]
    .reverse()
    .find((artifact) => FOLLOWUP_ARTIFACT_TYPES.has(artifact.artifact_type));

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
  const [streamState, setStreamState] = useState<"idle" | "live" | "reconnecting">("idle");
  const [lastStreamEventType, setLastStreamEventType] = useState<string | null>(null);
  const [lastStreamEventId, setLastStreamEventId] = useState<number | null>(null);
  const refreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const selectedSession =
    sessions.find((session) => session.id === selectedSessionId) ?? null;

  async function loadSessions(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const sessionResponse = await apiClient.listSessions();
      const knowledgeResponse = await apiClient.listKnowledge();
      setSessions(sessionResponse.items);
      setKnowledgeItems(knowledgeResponse.items);
      startTransition(() => {
        setSelectedSessionId((current) => current ?? sessionResponse.items[0]?.id ?? null);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
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
        jiraSubtasksSummary,
        subtaskGraphSummary,
        subtaskProgressSummary,
      ] = await Promise.all([
        Promise.resolve(buildFollowupContext(artifacts.items, events.items)),
        buildPlanningSummary(artifacts.items, events.items),
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
        jiraSubtasksSummary,
        subtaskGraphSummary,
        subtaskProgressSummary,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session detail");
    }
  }

  async function refreshSelected(): Promise<void> {
    await loadSessions();
    if (selectedSessionId !== null) {
      await loadBundle(selectedSessionId);
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
          />
          <SessionList
            onSelect={(sessionId) => setSelectedSessionId(sessionId)}
            selectedSessionId={selectedSessionId}
            sessions={sessions}
          />
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
