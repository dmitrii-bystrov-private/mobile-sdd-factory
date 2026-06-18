import { useState } from "react";

import { apiClient } from "../api/client";
import { useToast } from "./ToastProvider";
import type { InteractiveStateSummary, RuntimeSessionStateSummary, Session } from "../types";

type OperatorActionsProps = {
  session: Session;
  interactiveStateSummary: InteractiveStateSummary | null;
  runtimeStateSummary: RuntimeSessionStateSummary | null;
  onRefresh: () => Promise<void>;
};

type ActionDefinition = {
  label: string;
  description: string;
  disabled: boolean;
  strong?: boolean;
  danger?: boolean;
  confirmMessage?: string;
  onClick: () => Promise<void>;
};

export function OperatorActions({
  session,
  interactiveStateSummary,
  runtimeStateSummary,
  onRefresh,
}: OperatorActionsProps): JSX.Element {
  const { showActivity, clearActivity, showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, activityLabel?: string): Promise<void> {
    setBusy(true);
    setError(null);
    if (activityLabel) {
      showActivity(activityLabel);
    }
    try {
      await action();
      await onRefresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown request error";
      setError(message);
      showToast(message, "error");
    } finally {
      if (activityLabel) {
        clearActivity();
      }
      setBusy(false);
    }
  }

  const canRefreshSnapshot =
    session.status === "active" ||
    (session.status === "completed" &&
      session.workflow_profile === "story_full" &&
      ["mr_handoff_completed", "send_to_test_completed"].includes(session.current_stage));
  const canStartSubtaskGraph =
    session.workflow_profile === "story_full" &&
    session.status === "waiting_for_operator" &&
    session.current_stage === "subtask_creation_requested" &&
    interactiveStateSummary?.sourceReason === "subtask_creation_failed";
  const canCreateSubtasksFromPlan =
    session.workflow_profile === "story_full" &&
    session.current_stage === "subtask_creation_requested" &&
    (
      interactiveStateSummary?.sourceReason === "subtask_creation_failed" ||
      session.status === "active" ||
      session.status === "waiting_for_operator"
    );
  const hasStageSpecificDeliveryRetry =
    session.current_stage === "mr_handoff_failed" ||
    session.current_stage === "send_to_test_failed";
  const needsInteractiveReply =
    session.status === "waiting_for_operator" &&
    interactiveStateSummary?.available === true &&
    interactiveStateSummary.needsOperatorInput;
  const requiresRuntimeReactivation =
    session.status === "waiting_for_operator" &&
    interactiveStateSummary?.resumeStrategy === "reactivate_only";
  const supportsGenericRecovery =
    session.status === "waiting_for_operator" &&
    !needsInteractiveReply &&
    interactiveStateSummary?.sourceReason !== "boy_scout_findings" &&
    interactiveStateSummary?.sourceReason !== "subtask_creation_failed" &&
    session.current_stage !== "subtask_creation_requested" &&
    !hasStageSpecificDeliveryRetry &&
    !requiresRuntimeReactivation;
  const canSkipCurrentSubtask =
    session.workflow_profile === "story_full" &&
    session.status === "waiting_for_operator" &&
    session.current_stage === "subtask_implementation_requested";
  const dailyActions: ActionDefinition[] = [];
  const runtimeSessionActions: ActionDefinition[] = [];
  dailyActions.push({
    label: "Refresh task snapshot",
    description: "Pull the latest task snapshot into this run and reconcile any task-side changes.",
    disabled: busy || !canRefreshSnapshot,
    onClick: () => run(() => apiClient.refreshSnapshot(session.id)),
  });
  if (runtimeStateSummary?.available) {
    const visibleRuntimeRoles = runtimeStateSummary.roles.filter((role) => role.roleName !== "task-coordinator");
    runtimeSessionActions.push({
      label: "Stop all live runtimes",
      description: "Stop every live lane runtime in this session while keeping the task files intact.",
      disabled: busy || visibleRuntimeRoles.every((role) => role.status === "stopped"),
      onClick: () => run(() => apiClient.stopRuntimeSession(session.id)),
    });
    runtimeSessionActions.push({
      label: "Restart all runtimes",
      description: "Start the stopped runtime session again and relaunch its lane runtimes.",
      disabled: busy || visibleRuntimeRoles.some((role) => role.status !== "stopped"),
      onClick: () => run(() => apiClient.restartRuntimeSession(session.id)),
    });
  }

  const recoveryActions: ActionDefinition[] = [];
  recoveryActions.push({
    label: "Pause session",
    description: "Pause the current workflow so no new automated steps start until you explicitly resume it.",
    disabled: busy || session.status !== "active",
    confirmMessage:
      "Pause this session? The coordinator will stop advancing it until you resume it.",
    onClick: () => run(() => apiClient.pauseSession(session.id)),
  });
  if (session.status === "paused" || supportsGenericRecovery) {
    recoveryActions.push({
      label: "Resume session",
      description: "Resume a paused or operator-blocked session after the external blocker has been fixed.",
      disabled: busy,
      onClick: () => run(() => apiClient.resumeSession(session.id)),
    });
  }
  if (supportsGenericRecovery) {
    recoveryActions.push({
      label: "Retry current stage",
      description: "Retry the current stage after a waiting-for-operator interruption without changing the routed work.",
      disabled: busy,
      onClick: () => run(() => apiClient.retrySession(session.id)),
    });
  }
  if (canCreateSubtasksFromPlan) {
    recoveryActions.push({
      label: "Create Jira subtasks",
      description: "Retry Jira subtask materialization after the automatic story setup failed before execution could start.",
      disabled: busy,
      onClick: () => run(() => apiClient.createSubtasksFromPlan(session.id), "Creating Jira subtasks…"),
    });
  }
  if (canStartSubtaskGraph) {
    recoveryActions.push({
      label: "Start subtask graph",
      description: "Force story subtask execution from a recovery checkpoint when Jira subtasks already exist and only graph dispatch remains.",
      disabled: busy,
      strong: true,
      onClick: () => run(() => apiClient.startSubtaskGraph(session.id), "Starting subtask graph…"),
    });
  }
  if (canSkipCurrentSubtask) {
    recoveryActions.push({
      label: "Skip current subtask",
      description: "Skip the currently blocked subtask in this run and continue to the downstream quality gates.",
      disabled: busy,
      danger: true,
      onClick: async () => {
        const reason = window.prompt("Reason for skipping the current subtask in this run:");
        if (reason === null) {
          return;
        }
        const normalizedReason = reason.trim();
        if (!normalizedReason) {
          setError("Subtask skip reason is required");
          showToast("Subtask skip reason is required", "error");
          return;
        }
        await run(
          () => apiClient.skipCurrentSubtask(session.id, normalizedReason),
          "Skipping current subtask…",
        );
      },
    });
  }
  const cleanupActions: ActionDefinition[] = [
    {
      label: "Soft cleanup",
      description:
        "Safely clean this task: keep local state for open work, but fully clean closed tasks when Jira status allows it.",
      disabled: busy,
      confirmMessage:
        "Run safe cleanup for this task? Open tasks keep their local state, while closed tasks are cleaned fully.",
      onClick: () => run(() => apiClient.cleanupTask(session.id, "smart"), "Running safe cleanup…"),
    },
    {
      label: "Force cleanup",
      description: "Fully remove task snapshot and runtime residue regardless of Jira status safeguards.",
      disabled: busy,
      danger: true,
      confirmMessage:
        "Force full cleanup for this task regardless of status? This will remove the task snapshot and worktree.",
      onClick: () => run(() => apiClient.cleanupTask(session.id, "full", true), "Removing task state…"),
    },
  ];

  const runControlActions: ActionDefinition[] = [...dailyActions, ...recoveryActions];

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Control</p>
        </div>
      </div>

      <div className="operator-actions-two-column">
        <div className="operator-action-group">
          <div className="operator-action-inline-heading">
            <strong>Run Controls</strong>
            <p className="form-help">
              Use these actions to refresh task state, pause the session, or recover a blocked run.
            </p>
          </div>
          <div className="operator-actions-toolbar">
            {runControlActions.map((action) => (
              <button
                key={action.label}
                className={`action-button${action.strong ? " action-button-strong" : ""}${action.danger ? " action-button-danger" : ""}`}
                disabled={action.disabled}
                onClick={() => {
                  if (action.confirmMessage && !window.confirm(action.confirmMessage)) {
                    return;
                  }
                  void action.onClick();
                }}
                title={action.description}
                type="button"
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>

        <div className="operator-action-group">
          {runtimeSessionActions.length > 0 ? (
            <div className="operator-action-group">
              <div className="operator-action-inline-heading">
                <strong>Runtime Session</strong>
                <p className="form-help">Use these only when you need to stop or relaunch every live runtime at once.</p>
              </div>
              <div className="operator-actions-toolbar">
                {runtimeSessionActions.map((action) => (
                  <button
                    key={action.label}
                    className="action-button"
                    disabled={action.disabled}
                    onClick={() => {
                      if (action.confirmMessage && !window.confirm(action.confirmMessage)) {
                        return;
                      }
                      void action.onClick();
                    }}
                    title={action.description}
                    type="button"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {cleanupActions.length > 0 ? (
        <div className="operator-action-group operator-action-group-wide">
          <div className="operator-action-inline-heading">
            <strong>Cleanup</strong>
            <p className="form-help">
              Use these only when you need to clear runtime residue or remove local task state.
            </p>
          </div>
          <div className="operator-actions-toolbar operator-actions-toolbar-horizontal">
            {cleanupActions.map((action) => (
              <button
                key={action.label}
                className={`action-button${action.strong ? " action-button-strong" : ""}${action.danger ? " action-button-danger" : ""}`}
                disabled={action.disabled}
                onClick={() => {
                  if (action.confirmMessage && !window.confirm(action.confirmMessage)) {
                    return;
                  }
                  void action.onClick();
                }}
                title={action.description}
                type="button"
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
