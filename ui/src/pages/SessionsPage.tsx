import { startTransition, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import { SessionDetail } from "../components/SessionDetail";
import { SessionList } from "../components/SessionList";
import type { Session, SessionBundle } from "../types";

export function SessionsPage(): JSX.Element {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [bundle, setBundle] = useState<SessionBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      setBundle({
        roles: roles.items,
        artifacts: artifacts.items,
        events: events.items,
        workItems: workItems.items,
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

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">SDD Factory</p>
          <h1>Operator Console</h1>
        </div>
        <button
          className="action-button action-button-strong"
          onClick={() => void refreshSelected()}
          type="button"
        >
          Refresh Surface
        </button>
      </header>

      {error ? <div className="error-banner top-error">{error}</div> : null}

      <div className="page-layout">
        <SessionList
          onSelect={(sessionId) => setSelectedSessionId(sessionId)}
          selectedSessionId={selectedSessionId}
          sessions={sessions}
        />
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
