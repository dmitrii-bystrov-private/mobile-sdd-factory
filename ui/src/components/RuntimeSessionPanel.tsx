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
              <span>tmux socket</span>
              <strong>{runtimeStateSummary.tmuxSocketPath ?? "n/a"}</strong>
            </div>
            <div className="table-row">
              <span>Role count</span>
              <strong>{runtimeStateSummary.roles.length}</strong>
            </div>
          </div>

          {runtimeStateSummary.tmuxAttachCommand ? (
            <div className="artifact-card">
              <div className="artifact-meta">
                <span>tmux</span>
                <strong>Attach Session</strong>
              </div>
              <pre className="artifact-path">{runtimeStateSummary.tmuxAttachCommand}</pre>
            </div>
          ) : null}

          {runtimeStateSummary.lastAutoRecovery ? (
            <div className="artifact-card">
              <div className="artifact-meta">
                <span>auto recovery</span>
                <strong>{runtimeStateSummary.lastAutoRecovery.roleName ?? "unknown role"}</strong>
              </div>
              <p className="artifact-path">
                recovered at stage {runtimeStateSummary.lastAutoRecovery.currentStage ?? "unknown"} ·
                event #{runtimeStateSummary.lastAutoRecovery.eventId}
              </p>
              <p className="artifact-path">
                replaced {runtimeStateSummary.lastAutoRecovery.deadRuntimeHandle ?? "unknown handle"} with{" "}
                {runtimeStateSummary.lastAutoRecovery.runtimeHandle ?? "unknown handle"}
              </p>
            </div>
          ) : null}

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
                {role.tmuxAttachCommand ? (
                  <pre className="artifact-path">{role.tmuxAttachCommand}</pre>
                ) : null}
                {role.tmuxCaptureCommand ? (
                  <pre className="artifact-path">{role.tmuxCaptureCommand}</pre>
                ) : null}
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

      <div className="artifact-card">
        <div className="artifact-meta">
          <span>cleanup</span>
          <strong>Task Cleanup</strong>
        </div>
        <p className="path-label">
          Soft cleanup stops live runtime and removes task-local runtime residue while keeping the
          task worktree. Full cleanup removes the whole task snapshot and worktree; force mode
          skips the closed-status gate.
        </p>
        <div className="actions-grid">
          <button
            className="action-button"
            disabled={busy}
            onClick={() => run(() => apiClient.cleanupTask(session.id, "soft"))}
            type="button"
          >
            Clean Runtime Residue
          </button>
          <button
            className="action-button"
            disabled={busy}
            onClick={() => run(() => apiClient.cleanupTask(session.id, "full"))}
            type="button"
          >
            Full Cleanup If Closed
          </button>
          <button
            className="action-button"
            disabled={busy}
            onClick={() => run(() => apiClient.cleanupTask(session.id, "full", true))}
            type="button"
          >
            Force Full Cleanup
          </button>
        </div>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
