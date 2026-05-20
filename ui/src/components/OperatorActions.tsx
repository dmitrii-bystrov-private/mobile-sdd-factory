import { useState } from "react";

import { apiClient } from "../api/client";
import type { InteractiveStateSummary, Session } from "../types";

type OperatorActionsProps = {
  session: Session;
  interactiveStateSummary: InteractiveStateSummary | null;
  onRefresh: () => Promise<void>;
};

type ActionDefinition = {
  label: string;
  description: string;
  disabled: boolean;
  strong?: boolean;
  onClick: () => Promise<void>;
};

export function OperatorActions({
  session,
  interactiveStateSummary,
  onRefresh,
}: OperatorActionsProps): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mrPlatform, setMrPlatform] = useState<"ios" | "android">(
    session.task_key.startsWith("ANDR-") ? "android" : "ios",
  );
  const [mrId, setMrId] = useState("");
  const [qaComment, setQaComment] = useState("");
  const [boyScoutSkipReason, setBoyScoutSkipReason] = useState("");
  const [runtimeInput, setRuntimeInput] = useState("");

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

  async function handleMrIngest(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedMrId = mrId.trim();
    if (normalizedMrId.length === 0) {
      setError("MR id is required");
      return;
    }
    await run(async () => {
      await apiClient.ingestMrComments(session.id, mrPlatform, normalizedMrId);
      setMrId("");
    });
  }

  async function handleQaReopen(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedComment = qaComment.trim();
    if (normalizedComment.length === 0) {
      setError("QA follow-up comment is required");
      return;
    }
    await run(async () => {
      await apiClient.reopenFromQa(session.id, normalizedComment);
      setQaComment("");
    });
  }

  async function handleBoyScoutSkip(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedReason = boyScoutSkipReason.trim();
    if (normalizedReason.length === 0) {
      setError("Boy Scout skip reason is required");
      return;
    }
    await run(async () => {
      await apiClient.skipBoyScout(session.id, normalizedReason);
      setBoyScoutSkipReason("");
    });
  }

  async function handleBoyScoutResolution(
    resolution: "implement_now" | "create_tech_debt",
  ): Promise<void> {
    await run(async () => {
      await apiClient.resolveBoyScoutFindings(session.id, resolution);
    });
  }

  async function handleRuntimeInput(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedInput = runtimeInput.trim();
    if (normalizedInput.length === 0) {
      setError("Runtime input is required");
      return;
    }
    await run(async () => {
      await apiClient.sendRuntimeInput(session.id, normalizedInput);
      setRuntimeInput("");
    });
  }

  const canOpenFollowup = session.status === "completed";
  const canRefreshSnapshot =
    session.status === "active" ||
    (session.status === "completed" &&
      session.workflow_profile === "story_full" &&
      ["mr_handoff_completed", "send_to_test_completed"].includes(session.current_stage));
  const canSkipBoyScout =
    session.current_stage === "boy_scout_requested" &&
    session.status === "waiting_for_operator" &&
    interactiveStateSummary?.sourceReason === "boy_scout_findings" &&
    session.policy["boy_scout_policy"] === "enabled";
  const canResolveBoyScoutFindings =
    session.current_stage === "boy_scout_requested" &&
    session.status === "waiting_for_operator" &&
    interactiveStateSummary?.sourceReason === "boy_scout_findings";
  const canStartSubtaskGraph =
    session.workflow_profile === "story_full" &&
    session.status === "waiting_for_operator" &&
    session.current_stage === "subtask_creation_requested" &&
    interactiveStateSummary?.sourceReason === "subtask_creation_failed";
  const canRefreshSubtaskState =
    session.status === "active" &&
    session.workflow_profile === "story_full" &&
    ["implementation_requested", "subtask_implementation_requested"].includes(session.current_stage);
  const canCreateSubtasksFromPlan =
    session.workflow_profile === "story_full" &&
    session.status === "waiting_for_operator" &&
    session.current_stage === "subtask_creation_requested" &&
    interactiveStateSummary?.sourceReason === "subtask_creation_failed";
  const canCreateMr = session.current_stage === "mr_handoff_failed";
  const canSendToTest = session.current_stage === "send_to_test_failed";
  const hasStageSpecificDeliveryRetry = canCreateMr || canSendToTest;
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
    !hasStageSpecificDeliveryRetry &&
    !requiresRuntimeReactivation;
  const canSendRuntimeInput =
    needsInteractiveReply;

  const dailyActions: ActionDefinition[] = [];
  if (canRefreshSnapshot) {
    dailyActions.push({
      label: "Refresh Snapshot",
      description: "Refresh the task snapshot while the session is active, or reopen a completed story flow when new subtasks appear after delivery.",
      disabled: busy,
      onClick: () => run(() => apiClient.refreshSnapshot(session.id)),
    });
  }
  if (canRefreshSubtaskState) {
    dailyActions.push({
      label: "Refresh Subtask State",
      description: "Refresh Jira subtask state and reconcile the remaining story execution queue around the currently active subtask.",
      disabled: busy,
      onClick: () => run(() => apiClient.refreshSubtaskState(session.id)),
    });
  }

  const recoveryActions: ActionDefinition[] = [];
  if (session.status === "active") {
    recoveryActions.push({
      label: "Pause Session",
      description: "Pause the current workflow so the coordinator stops advancing the session automatically.",
      disabled: busy,
      strong: true,
      onClick: () => run(() => apiClient.pauseSession(session.id)),
    });
  }
  if (session.status === "paused" || supportsGenericRecovery) {
    recoveryActions.push({
      label: "Resume Session",
      description: "Resume a paused or operator-blocked session after the external blocker has been fixed.",
      disabled: busy,
      onClick: () => run(() => apiClient.resumeSession(session.id)),
    });
  }
  if (supportsGenericRecovery) {
    recoveryActions.push({
      label: "Retry Current Stage",
      description: "Retry the current stage after a waiting-for-operator interruption without changing the routed work.",
      disabled: busy,
      onClick: () => run(() => apiClient.retrySession(session.id)),
    });
  }
  if (canCreateSubtasksFromPlan) {
    recoveryActions.push({
      label: "Create Jira Subtasks",
      description: "Retry Jira subtask materialization after the automatic story setup failed before execution could start.",
      disabled: busy,
      onClick: () => run(() => apiClient.createSubtasksFromPlan(session.id)),
    });
  }
  if (canStartSubtaskGraph) {
    recoveryActions.push({
      label: "Start Subtask Graph",
      description: "Force story subtask execution from a recovery checkpoint when Jira subtasks already exist and only graph dispatch remains.",
      disabled: busy,
      strong: true,
      onClick: () => run(() => apiClient.startSubtaskGraph(session.id)),
    });
  }
  if (canCreateMr) {
    recoveryActions.push({
      label: "Retry MR Handoff",
      description: "Manually rerun MR handoff only after automatic delivery failed at the merge request creation step.",
      disabled: busy,
      strong: true,
      onClick: () => run(() => apiClient.createMr(session.id)),
    });
  }
  if (canSendToTest) {
    recoveryActions.push({
      label: "Retry Send To Test",
      description: "Manually rerun send-to-test only after automatic delivery failed after MR handoff completed.",
      disabled: busy,
      strong: true,
      onClick: () => run(() => apiClient.sendToTest(session.id)),
    });
  }

  function renderActionGroup(
    title: string,
    _eyebrow: string,
    _summary: string,
    actions: ActionDefinition[],
  ): JSX.Element | null {
    if (actions.length === 0) {
      return null;
    }
    return (
      <div className="operator-action-group">
        <div className="operator-action-inline-heading">
          <strong>{title}</strong>
        </div>
        <div className="actions-grid operator-actions-grid">
          {actions.map((action) => (
            <div key={action.label} className="operator-action-card">
              <button
                className={`action-button${action.strong ? " action-button-strong" : ""}`}
                disabled={action.disabled}
                onClick={() => void action.onClick()}
                title={action.description}
                type="button"
              >
                {action.label}
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Control</p>
          <h3>Operator Actions</h3>
        </div>
      </div>

      {renderActionGroup(
        "Daily Flow",
        "Daily",
        "These are the operator actions that belong to normal day-to-day task handling.",
        dailyActions,
      )}

      {renderActionGroup(
        "Recovery And Debug",
        "Recovery",
        "Use these controls only when the happy path is blocked or you need to intervene manually.",
        recoveryActions,
      )}

      {canSendRuntimeInput ? (
        <div className="operator-followup-stack">
          <div className="operator-followup-copy">
            <p className="eyebrow">Interactive Recovery</p>
            <h4>Runtime Input</h4>
          </div>

          <form className="followup-form" onSubmit={(event) => void handleRuntimeInput(event)}>
            <label className="form-field">
              <span>Runtime Input</span>
              <textarea
                className="text-area-input"
                disabled={busy || !canSendRuntimeInput}
                onChange={(event) => setRuntimeInput(event.target.value)}
                placeholder="Examples: 1 or another direct reply required by the live agent session."
                rows={3}
                value={runtimeInput}
              />
            </label>
              <button
                className="action-button"
                disabled={busy || !canSendRuntimeInput}
                title="Send a direct reply into the live runtime session after the agent asked the operator for input."
                type="submit"
            >
              Send Runtime Input
            </button>
          </form>
        </div>
      ) : null}

      {canResolveBoyScoutFindings || canSkipBoyScout ? (
        <div className="operator-followup-stack">
          <div className="operator-followup-copy">
            <p className="eyebrow">Optional Lane</p>
            <h4>Boy Scout</h4>
          </div>

          {canResolveBoyScoutFindings ? (
            <div className="actions-grid operator-actions-grid">
              <div className="operator-action-card">
                <button
                  className="action-button action-button-strong"
                  disabled={busy || !canResolveBoyScoutFindings}
                  onClick={() => void handleBoyScoutResolution("implement_now")}
                  title="Send every Boy Scout finding back to the coding lane immediately."
                  type="button"
                >
                  Implement Boy Scout Findings
                </button>
              </div>
              <div className="operator-action-card">
                <button
                  className="action-button"
                  disabled={busy || !canResolveBoyScoutFindings}
                  onClick={() => void handleBoyScoutResolution("create_tech_debt")}
                  title="Create tech-debt stories for the old-code findings and route the remaining actionable findings back to the coder."
                  type="button"
                >
                  Create Tech Debt And Continue
                </button>
              </div>
            </div>
          ) : null}

          {canSkipBoyScout ? (
            <form className="followup-form" onSubmit={(event) => void handleBoyScoutSkip(event)}>
              <label className="form-field">
                <span>Skip Reason</span>
                <textarea
                  className="text-area-input"
                  disabled={busy || !canSkipBoyScout}
                  onChange={(event) => setBoyScoutSkipReason(event.target.value)}
                  placeholder="Example: Findings acknowledged; continue with final verification and track refactors separately."
                  rows={3}
                  value={boyScoutSkipReason}
                />
              </label>
              <button
                className="action-button"
                disabled={busy || !canSkipBoyScout}
                title="Skip the optional Boy Scout lane for this session and continue with the downstream flow."
                type="submit"
              >
                Skip Boy Scout
              </button>
            </form>
          ) : null}
        </div>
      ) : null}

      {canOpenFollowup ? (
        <div className="operator-followup-stack">
          <div className="operator-followup-copy">
            <p className="eyebrow">Follow-up Intake</p>
            <h4>Reopen Completed Session</h4>
          </div>

          <form className="followup-form" onSubmit={(event) => void handleMrIngest(event)}>
            <div className="followup-form-grid">
              <label className="form-field">
                <span>MR Platform</span>
                <select
                  className="select-input"
                  disabled={busy || !canOpenFollowup}
                  onChange={(event) => setMrPlatform(event.target.value as "ios" | "android")}
                  value={mrPlatform}
                >
                  <option value="ios">ios</option>
                  <option value="android">android</option>
                </select>
              </label>
              <label className="form-field">
                <span>MR Id</span>
                <input
                  className="text-input"
                  disabled={busy || !canOpenFollowup}
                  onChange={(event) => setMrId(event.target.value)}
                  placeholder="2942"
                  value={mrId}
                />
              </label>
            </div>
            <button
              className="action-button"
              disabled={busy || !canOpenFollowup}
              title="Pull unresolved merge request comments into the completed session and reopen the follow-up flow."
              type="submit"
            >
              Ingest MR Comments
            </button>
          </form>

          <form className="followup-form" onSubmit={(event) => void handleQaReopen(event)}>
            <label className="form-field">
              <span>QA Follow-up Comment</span>
              <textarea
                className="text-area-input"
                disabled={busy || !canOpenFollowup}
                onChange={(event) => setQaComment(event.target.value)}
                placeholder="QA: still broken on edge case"
                rows={4}
                value={qaComment}
              />
            </label>
            <button
              className="action-button"
              disabled={busy || !canOpenFollowup}
              title="Reopen the completed session from a QA comment so the follow-up execution flow can resume."
              type="submit"
            >
              Reopen From QA
            </button>
          </form>
        </div>
      ) : null}

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
