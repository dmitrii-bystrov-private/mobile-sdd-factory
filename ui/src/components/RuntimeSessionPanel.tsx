import { useState } from "react";

import { apiClient } from "../api/client";
import { roleDisplayName } from "../roleDisplay";
import { stageDisplayName } from "../stageDisplay";
import type { RuntimeSessionStateSummary, Session } from "../types";

type RuntimeSessionPanelProps = {
  runtimeStateSummary: RuntimeSessionStateSummary | null;
  session: Session;
  onRefresh: () => Promise<void>;
};

function runtimeRoleStatusLabel(status: string): string {
  switch (status) {
    case "running":
      return "Live";
    case "stopped":
      return "Stopped";
    case "waiting":
      return "Waiting";
    default:
      return status;
  }
}

export function RuntimeSessionPanel({
  runtimeStateSummary,
  session,
  onRefresh,
}: RuntimeSessionPanelProps): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCleanup, setShowCleanup] = useState(false);
  const [debugNotice, setDebugNotice] = useState<string | null>(null);

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

  async function copyDebugCommand(
    command: string | null | undefined,
    successMessage: string,
  ): Promise<void> {
    if (!command) {
      return;
    }
    try {
      await navigator.clipboard.writeText(command);
      setDebugNotice(successMessage);
    } catch {
      setDebugNotice("Clipboard copy failed.");
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
          {(() => {
            const visibleRoles = runtimeStateSummary.roles.filter((role) => role.roleName !== "task-coordinator");
            return (
              <>
          <div className="table-list">
            <div className="table-row">
              <span>Live lanes</span>
              <strong>
                {visibleRoles.filter((role) => role.status === "running").length}/
                {visibleRoles.length}
              </strong>
            </div>
            <div className="table-row">
              <span>Stopped lanes</span>
              <strong>{visibleRoles.filter((role) => role.status === "stopped").length}</strong>
            </div>
            <div className="table-row">
              <span>Session runtime</span>
              <strong>{runtimeStateSummary.runtimeSessionId ? "Available" : "Unknown"}</strong>
            </div>
          </div>

          {runtimeStateSummary.lastAutoRecovery ? (
            <div className="artifact-card">
              <div className="artifact-meta">
                <span>auto recovery</span>
                <strong>{roleDisplayName(runtimeStateSummary.lastAutoRecovery.roleName)}</strong>
              </div>
              <p className="artifact-path">
                Runtime recovery already happened at {stageDisplayName(runtimeStateSummary.lastAutoRecovery.currentStage)}.
                Latest recovery event: #{runtimeStateSummary.lastAutoRecovery.eventId}.
              </p>
            </div>
          ) : null}

          <div className="actions-grid">
            <button
              className="action-button"
              disabled={busy || visibleRoles.every((role) => role.status === "stopped")}
              onClick={() => run(() => apiClient.stopRuntimeSession(session.id))}
              title="Stop every live role runtime in this session while keeping the task files intact."
              type="button"
            >
              Stop Runtime Session
            </button>
            <button
              className="action-button"
              disabled={busy || visibleRoles.some((role) => role.status !== "stopped")}
              onClick={() => run(() => apiClient.restartRuntimeSession(session.id))}
              title="Start the stopped runtime session again and relaunch its role runtimes."
              type="button"
            >
              Restart Runtime Session
            </button>
            <button
              className="action-button"
              disabled={busy}
              onClick={() => run(() => onRefresh())}
              title="Refresh the runtime state surface without changing the workflow."
              type="button"
            >
              Refresh Runtime View
            </button>
          </div>

          <div className="artifact-stack">
            {visibleRoles.map((role) => (
              <article className="artifact-card" key={role.roleName}>
                <div className="artifact-meta">
                  <span>{runtimeRoleStatusLabel(role.status)}</span>
                  <strong>{roleDisplayName(role.roleName)}</strong>
                </div>
                <p className="artifact-path">
                  {role.status === "running"
                    ? "This lane currently has a live runtime."
                    : role.status === "stopped"
                      ? "This lane is currently stopped."
                      : "This lane is waiting on runtime or orchestration state."}
                </p>
                <button
                  className="action-button"
                  disabled={busy || role.runtimeHandle === null || role.status === "stopped"}
                  onClick={() => run(() => apiClient.stopRuntimeRole(session.id, role.roleName))}
                  title={`Stop the live runtime for ${roleDisplayName(role.roleName)} without stopping the whole session.`}
                  type="button"
                >
                  Stop Role Runtime
                </button>
                <button
                  className="action-button"
                  disabled={busy || role.status !== "stopped"}
                  onClick={() => run(() => apiClient.restartRuntimeRole(session.id, role.roleName))}
                  title={`Restart the stopped runtime for ${roleDisplayName(role.roleName)} inside this session.`}
                  type="button"
                >
                  Restart Role Runtime
                </button>
                {(role.tmuxAttachCommand || role.tmuxCaptureCommand || role.runtimeHandle) ? (
                  <details className="advanced-disclosure">
                    <summary>
                      <div>
                        <strong>Worker Console</strong>
                      </div>
                      <span className="chevron" aria-hidden="true" />
                    </summary>
                    <div className="advanced-disclosure-body">
                      <div className="actions-grid">
                        {role.tmuxAttachCommand ? (
                          <button
                            className="action-button"
                            onClick={() =>
                              void copyDebugCommand(
                                role.tmuxAttachCommand,
                                `${roleDisplayName(role.roleName)} attach command copied.`,
                              )
                            }
                            type="button"
                          >
                            Copy Console Command
                          </button>
                        ) : null}
                        {role.tmuxCaptureCommand ? (
                          <button
                            className="action-button"
                            onClick={() =>
                              void copyDebugCommand(
                                role.tmuxCaptureCommand,
                                `${roleDisplayName(role.roleName)} capture command copied.`,
                              )
                            }
                            type="button"
                          >
                            Copy Output Command
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </details>
                ) : null}
              </article>
            ))}
          </div>

          {(runtimeStateSummary.tmuxAttachCommand || runtimeStateSummary.tmuxSocketPath) ? (
            <details className="advanced-disclosure">
              <summary>
                <div>
                  <strong>Session Console</strong>
                </div>
                <span className="chevron" aria-hidden="true" />
              </summary>
              <div className="advanced-disclosure-body">
                {runtimeStateSummary.tmuxAttachCommand ? (
                  <button
                    className="action-button"
                    onClick={() =>
                      void copyDebugCommand(
                        runtimeStateSummary.tmuxAttachCommand,
                        "Session attach command copied.",
                      )
                    }
                    type="button"
                  >
                    Copy Session Console Command
                  </button>
                ) : null}
              </div>
            </details>
          ) : null}
              </>
            );
          })()}
        </>
      )}

      <div className="advanced-disclosure">
        <button
          className="advanced-disclosure-toggle"
          onClick={() => setShowCleanup((value) => !value)}
          aria-expanded={showCleanup}
          type="button"
        >
          <div>
            <strong>Cleanup And Residue Removal</strong>
          </div>
          <span className={`chevron${showCleanup ? " expanded" : ""}`} aria-hidden="true" />
        </button>
        {showCleanup ? (
          <div className="advanced-disclosure-body">
            <div className="actions-grid">
              <button
                className="action-button"
                disabled={busy}
                onClick={() => run(() => apiClient.cleanupTask(session.id, "soft"))}
                title="Stop runtime and remove task-local runtime residue while keeping the task worktree and snapshot."
                type="button"
              >
                Clean Runtime Residue
              </button>
              <button
                className="action-button"
                disabled={busy}
                onClick={() => run(() => apiClient.cleanupTask(session.id, "full"))}
                title="Remove the full task snapshot and worktree only if the task status allows closed-task cleanup."
                type="button"
              >
                Full Cleanup If Closed
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {debugNotice ? <p className="path-label">{debugNotice}</p> : null}
      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
