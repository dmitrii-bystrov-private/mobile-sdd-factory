import { useState } from "react";

import { apiClient } from "../api/client";
import type { RuntimeSessionStateSummary, Session } from "../types";

type RuntimeSessionPanelProps = {
  runtimeStateSummary: RuntimeSessionStateSummary | null;
  session: Session;
  onRefresh: () => Promise<void>;
};

export function RuntimeSessionPanel({
  runtimeStateSummary,
  session,
  onRefresh,
}: RuntimeSessionPanelProps): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown request error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h3>Runtime Session</h3>
        </div>
      </div>

      {runtimeStateSummary === null || !runtimeStateSummary.available ? (
        <p className="path-label">Runtime session state is not available.</p>
      ) : (
        <>
          <div className="table-list">
            <div className="table-row">
              <span>Runtime session</span>
              <strong>{runtimeStateSummary.runtimeSessionId ?? "unknown"}</strong>
            </div>
            <div className="table-row">
              <span>Role count</span>
              <strong>{runtimeStateSummary.roles.length}</strong>
            </div>
          </div>

          <div className="actions-grid">
            <button
              className="action-button"
              disabled={busy || runtimeStateSummary.roles.every((role) => role.status === "stopped")}
              onClick={() => run(() => apiClient.stopRuntimeSession(session.id))}
              type="button"
            >
              Stop Runtime Session
            </button>
            <button
              className="action-button"
              disabled={busy || runtimeStateSummary.roles.some((role) => role.status !== "stopped")}
              onClick={() => run(() => apiClient.restartRuntimeSession(session.id))}
              type="button"
            >
              Restart Runtime Session
            </button>
            <button
              className="action-button"
              disabled={busy}
              onClick={() => run(() => onRefresh())}
              type="button"
            >
              Refresh Runtime View
            </button>
          </div>

          <div className="artifact-stack">
            {runtimeStateSummary.roles.map((role) => (
              <article className="artifact-card" key={role.roleName}>
                <div className="artifact-meta">
                  <span>{role.status}</span>
                  <strong>{role.roleName}</strong>
                </div>
                <p className="artifact-path">
                  {role.runtimeBackend} · {role.runtimeHandle ?? "no handle"}
                </p>
                <button
                  className="action-button"
                  disabled={busy || role.runtimeHandle === null || role.status === "stopped"}
                  onClick={() => run(() => apiClient.stopRuntimeRole(session.id, role.roleName))}
                  type="button"
                >
                  Stop Role Runtime
                </button>
                <button
                  className="action-button"
                  disabled={busy || role.status !== "stopped"}
                  onClick={() => run(() => apiClient.restartRuntimeRole(session.id, role.roleName))}
                  type="button"
                >
                  Restart Role Runtime
                </button>
              </article>
            ))}
          </div>
        </>
      )}

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
