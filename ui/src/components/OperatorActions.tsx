import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { Role, Session } from "../types";

type OperatorActionsProps = {
  roles: Role[];
  session: Session;
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
  roles,
  session,
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
  const [knowledgeTitle, setKnowledgeTitle] = useState("");
  const [knowledgeScope, setKnowledgeScope] = useState("");
  const [knowledgeGuidance, setKnowledgeGuidance] = useState("");
  const [runtimeInput, setRuntimeInput] = useState("");
  const [redirectTargetRole, setRedirectTargetRole] = useState("");

  const allowedRedirectTargetsByStage: Record<string, string[]> = {
    bug_analysis_requested: ["bug-fixer"],
    story_spec_requested: ["story-spec-worker"],
    proposal_context_requested: ["proposal-context-worker"],
    requirements_requested: ["requirements-clarifier-worker"],
    acceptance_criteria_requested: ["acceptance-criteria-worker"],
    constraints_requested: ["constraints-worker"],
    spec_verification_requested: ["spec-verifier-worker"],
    task_decomposition_requested: ["task-decomposer-worker"],
    subtask_implementation_requested: ["implementer"],
    implementation_requested: ["implementer", "bug-fixer"],
    verification_requested: ["verification-coordinator"],
    verification_correction_requested: ["implementer", "bug-fixer"],
    self_review_requested: ["code-reviewer"],
    boy_scout_requested: ["code-scout"],
    boy_scout_correction_requested: ["implementer", "bug-fixer"],
    doc_harvest_requested: ["doc-harvest-worker"],
    mr_comments_analysis_requested: ["mr-comments-analyst-worker"],
    self_review_correction_requested: ["implementer", "bug-fixer"],
  };

  const availableRedirectTargets = allowedRedirectTargetsByStage[session.current_stage]
    ?.filter((roleName) => roleName !== session.current_owner)
    .filter((roleName) => roles.some((role) => role.role_name === roleName)) ?? [];

  const canRedirectSession =
    session.status === "waiting_for_operator" &&
    availableRedirectTargets.length > 0;

  useEffect(() => {
    if (availableRedirectTargets.length === 0) {
      if (redirectTargetRole !== "") {
        setRedirectTargetRole("");
      }
      return;
    }
    if (!availableRedirectTargets.includes(redirectTargetRole)) {
      setRedirectTargetRole(availableRedirectTargets[0] ?? "");
    }
  }, [availableRedirectTargets, redirectTargetRole]);

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

  async function handleKnowledge(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedTitle = knowledgeTitle.trim();
    const normalizedGuidance = knowledgeGuidance.trim();
    if (normalizedTitle.length === 0 || normalizedGuidance.length === 0) {
      setError("Knowledge title and guidance are required");
      return;
    }
    await run(async () => {
      await apiClient.createKnowledge(
        session.id,
        normalizedTitle,
        normalizedGuidance,
        knowledgeScope.trim(),
      );
      setKnowledgeTitle("");
      setKnowledgeScope("");
      setKnowledgeGuidance("");
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

  async function handleRedirectSession(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (redirectTargetRole.length === 0) {
      setError("Redirect target role is required");
      return;
    }
    await run(async () => {
      await apiClient.redirectSession(session.id, redirectTargetRole);
    });
  }

  const canOpenFollowup = session.status === "completed";
  const canRefreshSnapshot =
    session.status !== "completed" ||
    ["mr_handoff_completed", "send_to_test_completed", "qa_reopen_requested"].includes(session.current_stage);
  const canSkipBoyScout =
    session.current_stage === "boy_scout_requested" &&
    session.status === "waiting_for_operator" &&
    session.policy["boy_scout_policy"] === "enabled";
  const canResolveBoyScoutFindings =
    session.current_stage === "boy_scout_requested" &&
    session.status === "waiting_for_operator";
  const canStartSubtaskGraph =
    session.workflow_profile === "story_full" &&
    session.status === "waiting_for_operator" &&
    session.current_stage === "subtask_creation_requested";
  const canRefreshSubtaskState =
    session.status === "active" &&
    session.workflow_profile === "story_full" &&
    ["implementation_requested", "subtask_implementation_requested"].includes(session.current_stage);
  const canCreateSubtasksFromPlan =
    session.workflow_profile === "story_full" &&
    session.status === "waiting_for_operator" &&
    session.current_stage === "subtask_creation_requested";
  const canCreateMr = session.current_stage === "mr_handoff_failed";
  const canSendToTest = session.current_stage === "send_to_test_failed";
  const canSendRuntimeInput = session.status === "waiting_for_operator";

  const dailyActions: ActionDefinition[] = [];
  if (canRefreshSnapshot) {
    dailyActions.push({
      label: "Process Updates",
      description: "Refresh the task snapshot and let the coordinator decide whether to continue active work or reopen the flow from new subtasks and other external changes.",
      disabled: busy,
      onClick: () => run(() => apiClient.refreshSnapshot(session.id)),
    });
  }
  if (canRefreshSubtaskState) {
    dailyActions.push({
      label: "Refresh Subtask State",
      description: "Pull the latest subtask progress after new Jira subtasks or follow-up work appears.",
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
      onClick: () => run(() => apiClient.pauseSession(session.id)),
    });
  }
  if (["paused", "waiting_for_operator"].includes(session.status)) {
    recoveryActions.push({
      label: "Resume Session",
      description: "Resume a paused or operator-blocked session after the external blocker has been fixed.",
      disabled: busy,
      onClick: () => run(() => apiClient.resumeSession(session.id)),
    });
  }
  if (session.status === "waiting_for_operator") {
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
    eyebrow: string,
    summary: string,
    actions: ActionDefinition[],
  ): JSX.Element | null {
    if (actions.length === 0) {
      return null;
    }
    return (
      <div className="operator-action-group">
        <div className="operator-followup-copy">
          <p className="eyebrow">{eyebrow}</p>
          <h4>{title}</h4>
          <p className="path-label">{summary}</p>
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
              <p className="operator-action-description">{action.description}</p>
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
            <p className="path-label">
              Send a direct reply into the live role session after an interactive blocker escalates the task to operator.
            </p>
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

      {canRedirectSession ? (
        <div className="operator-followup-stack">
          <div className="operator-followup-copy">
            <p className="eyebrow">Recovery Redirect</p>
            <h4>Redirect Parked Work</h4>
            <p className="path-label">
              Reassign the current operator-blocked work item to another role that is valid for this same stage.
            </p>
          </div>

          <form className="followup-form" onSubmit={(event) => void handleRedirectSession(event)}>
            <label className="form-field">
              <span>Target Role</span>
              <select
                className="select-input"
                disabled={busy || !canRedirectSession}
                onChange={(event) => setRedirectTargetRole(event.target.value)}
                value={redirectTargetRole}
              >
                {availableRedirectTargets.map((roleName) => (
                  <option key={roleName} value={roleName}>
                    {roleName}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="action-button"
              disabled={busy || !canRedirectSession || redirectTargetRole.length === 0}
              title="Redirect the parked operator-blocked work item to another allowed role for the same stage."
              type="submit"
            >
              Redirect Session
            </button>
          </form>
        </div>
      ) : null}

      {canResolveBoyScoutFindings || canSkipBoyScout ? (
        <div className="operator-followup-stack">
          <div className="operator-followup-copy">
            <p className="eyebrow">Optional Lane</p>
            <h4>Boy Scout</h4>
            <p className="path-label">
              Resolve Boy Scout findings after the scout finishes. Use implement now when all findings should go back to the coder, create tech debt when only the old-code candidates should become separate stories, or skip the lane entirely when policy allows it.
            </p>
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
                <p className="operator-action-description">
                  Route all current Boy Scout findings back into a narrow correction pass without creating separate tech-debt stories.
                </p>
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
                <p className="operator-action-description">
                  Materialize separate tech-debt stories for the old-code findings, then send the remaining implement-now findings back to the coding lane.
                </p>
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
            <p className="path-label">
              Re-enter a completed session from merge request feedback or QA feedback.
            </p>
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

      <div className="operator-followup-stack">
        <div className="operator-followup-copy">
          <p className="eyebrow">Knowledge</p>
          <h4>Capture Project Knowledge</h4>
          <p className="path-label">
            Record a useful project convention, hidden constraint, or non-obvious implementation finding in the shared knowledge base.
          </p>
        </div>

        <form className="followup-form" onSubmit={(event) => void handleKnowledge(event)}>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Entry Title</span>
              <input
                className="text-input"
                disabled={busy}
                onChange={(event) => setKnowledgeTitle(event.target.value)}
                placeholder="Reuse existing formatter helper"
                value={knowledgeTitle}
              />
            </label>
            <label className="form-field">
              <span>Directory / Scope</span>
              <input
                className="text-input"
                disabled={busy}
                onChange={(event) => setKnowledgeScope(event.target.value)}
                placeholder="shared-formatting"
                value={knowledgeScope}
              />
            </label>
          </div>
          <label className="form-field">
            <span>Guidance</span>
            <textarea
              className="text-area-input"
              disabled={busy}
              onChange={(event) => setKnowledgeGuidance(event.target.value)}
              placeholder="Do not introduce a new helper here; use the existing shared formatter already used in this module."
              rows={4}
              value={knowledgeGuidance}
            />
          </label>
          <button
            className="action-button"
            disabled={busy}
            title="Create a reusable knowledge entry from this task for future sessions."
            type="submit"
          >
            Create Knowledge Entry
          </button>
        </form>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
