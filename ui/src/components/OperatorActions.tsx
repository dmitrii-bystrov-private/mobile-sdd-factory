import { useState } from "react";

import { apiClient } from "../api/client";
import type { Session } from "../types";

type OperatorActionsProps = {
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
  const [docHarvestSummary, setDocHarvestSummary] = useState("");
  const [boyScoutSkipReason, setBoyScoutSkipReason] = useState("");
  const [selfReviewOutcome, setSelfReviewOutcome] = useState<"passed" | "issues_found">("passed");
  const [selfReviewSummary, setSelfReviewSummary] = useState("");
  const [knowledgeTitle, setKnowledgeTitle] = useState("");
  const [knowledgeScope, setKnowledgeScope] = useState("");
  const [knowledgeGuidance, setKnowledgeGuidance] = useState("");
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

  async function handleDocHarvest(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedSummary = docHarvestSummary.trim();
    if (normalizedSummary.length === 0) {
      setError("Doc harvest summary is required");
      return;
    }
    await run(async () => {
      await apiClient.completeDocHarvest(session.id, normalizedSummary);
      setDocHarvestSummary("");
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

  async function handleSelfReview(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedSummary = selfReviewSummary.trim();
    if (normalizedSummary.length === 0) {
      setError("Self review summary is required");
      return;
    }
    await run(async () => {
      await apiClient.completeSelfReview(session.id, selfReviewOutcome, normalizedSummary);
      setSelfReviewSummary("");
      setSelfReviewOutcome("passed");
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
  const canCompleteSelfReview =
    session.current_stage === "self_review_requested" &&
    session.status === "active" &&
    session.policy["self_review_policy"] === "enabled";
  const canCompleteDocHarvest =
    session.policy["doc_harvest_policy"] === "enabled" &&
    (
      (session.current_stage === "doc_harvest_requested" && session.status === "active") ||
      (session.current_stage === "completed" && session.status === "completed")
    );
  const canStartSubtaskGraph =
    session.workflow_profile === "story_full" &&
    (
      (session.status === "active" && session.current_stage === "implementation_requested") ||
      (session.status === "waiting_for_operator" && session.current_stage === "subtask_creation_requested")
    );
  const canRefreshSubtaskState =
    session.status === "active" &&
    session.workflow_profile === "story_full" &&
    ["implementation_requested", "subtask_implementation_requested"].includes(session.current_stage);
  const canCreateSubtasksFromPlan =
    session.workflow_profile === "story_full" &&
    ["subtask_creation_requested", "implementation_requested", "subtask_implementation_requested", "verification_requested"].includes(
      session.current_stage,
    );
  const canCreateMr =
    session.status === "completed" && session.current_stage === "task_completed";
  const canSendToTest =
    session.status === "completed" && session.current_stage === "mr_handoff_completed";

  const dailyActions: ActionDefinition[] = [
    {
      label: "Process Updates",
      description: "Refresh the task snapshot and let the coordinator decide whether to continue active work or reopen the flow from new subtasks and other external changes.",
      disabled: busy || !canRefreshSnapshot,
      onClick: () => run(() => apiClient.refreshSnapshot(session.id)),
    },
    {
      label: "Refresh Subtask State",
      description: "Pull the latest subtask progress after new Jira subtasks or follow-up work appears.",
      disabled: busy || !canRefreshSubtaskState,
      onClick: () => run(() => apiClient.refreshSubtaskState(session.id)),
    },
    {
      label: "Create Jira Subtasks",
      description: "Materialize Jira subtasks from the current story plan when the session is ready for decomposition output.",
      disabled: busy || !canCreateSubtasksFromPlan,
      onClick: () => run(() => apiClient.createSubtasksFromPlan(session.id)),
    },
  ];

  const advancedActions: ActionDefinition[] = [
    {
      label: "Start Subtask Graph",
      description: "Explicitly start story subtask execution when the session is ready to branch into subtask work.",
      disabled: busy || !canStartSubtaskGraph,
      strong: true,
      onClick: () => run(() => apiClient.startSubtaskGraph(session.id)),
    },
    {
      label: "Run Loop Once",
      description: "Manually tick the coordinator loop once when you want to force a fresh reconciliation cycle.",
      disabled: busy,
      onClick: () => run(() => apiClient.runLoopOnce()),
    },
  ];

  const recoveryActions: ActionDefinition[] = [
    {
      label: "Pause Session",
      description: "Pause the current workflow so the coordinator stops advancing the session automatically.",
      disabled: busy || session.status !== "active",
      onClick: () => run(() => apiClient.pauseSession(session.id)),
    },
    {
      label: "Resume Session",
      description: "Resume a paused or operator-blocked session after the external blocker has been fixed.",
      disabled: busy || !["paused", "waiting_for_operator"].includes(session.status),
      onClick: () => run(() => apiClient.resumeSession(session.id)),
    },
    {
      label: "Retry Current Stage",
      description: "Retry the current stage after a waiting-for-operator interruption without changing the routed work.",
      disabled: busy || session.status !== "waiting_for_operator",
      onClick: () => run(() => apiClient.retrySession(session.id)),
    },
    {
      label: "Retry MR Handoff",
      description: "Manually rerun MR handoff only after automatic delivery failed at the merge request creation step.",
      disabled: busy || !canCreateMr,
      strong: true,
      onClick: () => run(() => apiClient.createMr(session.id)),
    },
    {
      label: "Retry Send To Test",
      description: "Manually rerun send-to-test only after automatic delivery failed after MR handoff completed.",
      disabled: busy || !canSendToTest,
      strong: true,
      onClick: () => run(() => apiClient.sendToTest(session.id)),
    },
  ];

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
        "Advanced Flow",
        "Advanced",
        "These actions are valid workflow controls, but they are used only in narrower lifecycle branches.",
        advancedActions,
      )}

      {renderActionGroup(
        "Recovery And Debug",
        "Recovery",
        "Use these controls only when the happy path is blocked or you need to intervene manually.",
        recoveryActions,
      )}

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
              disabled={busy || session.status !== "waiting_for_operator"}
              onChange={(event) => setRuntimeInput(event.target.value)}
              placeholder="Examples: 1 or another direct reply required by the live agent session."
              rows={3}
              value={runtimeInput}
            />
          </label>
          <button
            className="action-button"
            disabled={busy || session.status !== "waiting_for_operator"}
            type="submit"
          >
            Send Runtime Input
          </button>
        </form>
      </div>

      <div className="operator-followup-stack">
        <div className="operator-followup-copy">
          <p className="eyebrow">Optional Lane</p>
          <h4>Boy Scout</h4>
          <p className="path-label">
            Resolve Boy Scout findings after the scout finishes. Use implement now when all findings should go back to the coder, create tech debt when only the old-code candidates should become separate stories, or skip the lane entirely when policy allows it.
          </p>
        </div>

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
            type="submit"
          >
            Skip Boy Scout
          </button>
        </form>
      </div>

      <div className="operator-followup-stack">
        <div className="operator-followup-copy">
          <p className="eyebrow">Optional Lane</p>
          <h4>Self Review</h4>
          <p className="path-label">
            Record the explicit self-review outcome before final verification or route findings back into correction.
          </p>
        </div>

        <form className="followup-form" onSubmit={(event) => void handleSelfReview(event)}>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Outcome</span>
              <select
                className="select-input"
                disabled={busy || !canCompleteSelfReview}
                onChange={(event) => setSelfReviewOutcome(event.target.value as "passed" | "issues_found")}
                value={selfReviewOutcome}
              >
                <option value="passed">passed</option>
                <option value="issues_found">issues_found</option>
              </select>
            </label>
          </div>
          <label className="form-field">
            <span>Self Review Summary</span>
            <textarea
              className="text-area-input"
              disabled={busy || !canCompleteSelfReview}
              onChange={(event) => setSelfReviewSummary(event.target.value)}
              placeholder="Reviewed implementation; either no blocking issues were found or the main findings are listed here."
              rows={4}
              value={selfReviewSummary}
            />
          </label>
          <button
            className="action-button"
            disabled={busy || !canCompleteSelfReview}
            type="submit"
          >
            Complete Self Review
          </button>
        </form>
      </div>

      <div className="operator-followup-stack">
        <div className="operator-followup-copy">
          <p className="eyebrow">Optional Lane</p>
          <h4>Doc Harvest</h4>
          <p className="path-label">
            Record documentation harvest output as an explicit session stage before downstream handoff.
          </p>
        </div>

        <form className="followup-form" onSubmit={(event) => void handleDocHarvest(event)}>
          <label className="form-field">
            <span>Doc Harvest Summary</span>
            <textarea
              className="text-area-input"
              disabled={busy || !canCompleteDocHarvest}
              onChange={(event) => setDocHarvestSummary(event.target.value)}
              placeholder="README updated for the feature area and the current behavior is documented."
              rows={4}
              value={docHarvestSummary}
            />
          </label>
          <button
            className="action-button"
            disabled={busy || !canCompleteDocHarvest}
            type="submit"
          >
            Complete Doc Harvest
          </button>
        </form>
      </div>

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
            type="submit"
          >
            Reopen From QA
          </button>
        </form>
      </div>

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
          <button className="action-button" disabled={busy} type="submit">
            Create Knowledge Entry
          </button>
        </form>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
