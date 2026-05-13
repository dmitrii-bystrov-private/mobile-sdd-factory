import { startTransition, useEffect, useRef, useState } from "react";

import { apiClient, openSessionEventStream } from "../api/client";
import { SessionDetail } from "../components/SessionDetail";
import { SessionList } from "../components/SessionList";
import { SessionStartForm } from "../components/SessionStartForm";
import type {
  Artifact,
  EventItem,
  FollowupContext,
  Session,
  SessionBundle,
} from "../types";

const FOLLOWUP_ARTIFACT_TYPES = new Set(["mr_comments_markdown", "qa_reopen_comments"]);

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
      setSessions(sessionResponse.items);
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
      const followupContext = await buildFollowupContext(artifacts.items, events.items);
      setBundle({
        roles: roles.items,
        artifacts: artifacts.items,
        events: events.items,
        workItems: workItems.items,
        followupContext,
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
