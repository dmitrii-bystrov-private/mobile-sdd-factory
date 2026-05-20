import { useState } from "react";

import { apiClient } from "../api/client";
import { roleDisplayName } from "../roleDisplay";
import { stageDisplayName } from "../stageDisplay";
import { useToast } from "./ToastProvider";
import type { RuntimeSessionStateSummary, Session } from "../types";

type RuntimeSessionPanelProps = {
  runtimeStateSummary: RuntimeSessionStateSummary | null;
  session: Session;
  onRefresh: () => Promise<void>;
};

function roleFlowOrder(roleName: string, workflowProfile: Session["workflow_profile"]): number {
  const oneshotOrder = [
    "implementer",
    "code-reviewer",
    "verification-coordinator",
    "code-scout",
    "doc-harvest-worker",
    "mr-comments-analyst-worker",
  ];
  const bugFullOrder = [
    "implementer",
    "bug-fixer",
    "code-reviewer",
    "verification-coordinator",
    "code-scout",
    "doc-harvest-worker",
    "mr-comments-analyst-worker",
  ];
  const storyFullOrder = [
    "proposal-context-worker",
    "requirements-clarifier-worker",
    "acceptance-criteria-worker",
    "constraints-worker",
    "spec-verifier-worker",
    "story-spec-worker",
    "task-decomposer-worker",
    "implementer",
    "code-reviewer",
    "verification-coordinator",
    "code-scout",
    "doc-harvest-worker",
    "mr-comments-analyst-worker",
  ];

  const orderedRoles =
    workflowProfile === "story_full"
      ? storyFullOrder
      : workflowProfile === "bug_full"
        ? bugFullOrder
        : oneshotOrder;

  const index = orderedRoles.indexOf(roleName);
  return index === -1 ? orderedRoles.length + 1 : index;
}

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
  const { showToast } = useToast();

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
      showToast(successMessage);
    } catch {
      showToast("Copy failed", "error");
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h3>Runtime Controls</h3>
        </div>
      </div>

      {runtimeStateSummary === null || !runtimeStateSummary.available ? (
        <p className="path-label">Runtime session state is not available.</p>
      ) : (
        <>
          {(() => {
            const visibleRoles = runtimeStateSummary.roles.filter((role) => role.roleName !== "task-coordinator");
            const sortedRoles = [...visibleRoles].sort((left, right) => {
              const orderDelta =
                roleFlowOrder(left.roleName, session.workflow_profile) -
                roleFlowOrder(right.roleName, session.workflow_profile);
              if (orderDelta !== 0) {
                return orderDelta;
              }
              return left.roleName.localeCompare(right.roleName);
            });
            return (
              <>
                <div className="runtime-controls-stack">
                  <div className="table-list runtime-summary-list">
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
                  </div>

                  {runtimeStateSummary.lastAutoRecovery ? (
                    <div className="artifact-card runtime-note-card">
                      <div className="artifact-meta">
                        <span>auto recovery</span>
                        <strong>{roleDisplayName(runtimeStateSummary.lastAutoRecovery.roleName)}</strong>
                      </div>
                      <p className="artifact-path">
                        Runtime recovery already happened at {stageDisplayName(runtimeStateSummary.lastAutoRecovery.currentStage)}.
                      </p>
                    </div>
                  ) : null}

                  <div className="actions-grid runtime-session-actions">
                    <button
                      className="action-button"
                      disabled={busy || visibleRoles.every((role) => role.status === "stopped")}
                      onClick={() => run(() => apiClient.stopRuntimeSession(session.id))}
                      title="Stop every live lane runtime in this session while keeping the task files intact."
                      type="button"
                    >
                      Stop All Live Runtimes
                    </button>
                    <button
                      className="action-button"
                      disabled={busy || visibleRoles.some((role) => role.status !== "stopped")}
                      onClick={() => run(() => apiClient.restartRuntimeSession(session.id))}
                      title="Start the stopped runtime session again and relaunch its lane runtimes."
                      type="button"
                    >
                      Restart All Runtimes
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

                  <div className="artifact-stack runtime-role-stack">
                    {sortedRoles.map((role) => (
                      <article className="artifact-card runtime-role-card" key={role.roleName}>
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
                        <div className="actions-grid runtime-role-actions">
                          <button
                            className="action-button"
                            disabled={busy || role.runtimeHandle === null || role.status === "stopped"}
                            onClick={() => run(() => apiClient.stopRuntimeRole(session.id, role.roleName))}
                            title={`Stop the live runtime for ${roleDisplayName(role.roleName)} without stopping the whole session.`}
                            type="button"
                          >
                            Stop This Runtime
                          </button>
                          <button
                            className="action-button"
                            disabled={busy || role.status !== "stopped"}
                            onClick={() => run(() => apiClient.restartRuntimeRole(session.id, role.roleName))}
                            title={`Restart the stopped runtime for ${roleDisplayName(role.roleName)} inside this session.`}
                            type="button"
                          >
                            Restart This Runtime
                          </button>
                          {role.tmuxAttachCommand ? (
                            <button
                              className="action-button"
                              onClick={() =>
                                void copyDebugCommand(
                                  role.tmuxAttachCommand,
                                  `${roleDisplayName(role.roleName)} console command copied`,
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
                                  `${roleDisplayName(role.roleName)} output command copied`,
                                )
                              }
                              type="button"
                            >
                              Copy Output Command
                            </button>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              </>
            );
          })()}
        </>
      )}
      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
