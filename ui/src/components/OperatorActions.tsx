import { useState } from "react";

import { apiClient } from "../api/client";
import type { Session } from "../types";

type OperatorActionsProps = {
  session: Session;
  onRefresh: () => Promise<void>;
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
  const [selfReviewOutcome, setSelfReviewOutcome] = useState<"passed" | "issues_found">("passed");
  const [selfReviewSummary, setSelfReviewSummary] = useState("");
  const [reviewKnowledgeTitle, setReviewKnowledgeTitle] = useState("");
  const [reviewKnowledgeScope, setReviewKnowledgeScope] = useState("");
  const [reviewKnowledgeGuidance, setReviewKnowledgeGuidance] = useState("");
  const [sessionInsightTitle, setSessionInsightTitle] = useState("");
  const [sessionInsightScope, setSessionInsightScope] = useState("");
  const [sessionInsightGuidance, setSessionInsightGuidance] = useState("");

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

  async function handleReviewKnowledge(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedTitle = reviewKnowledgeTitle.trim();
    const normalizedGuidance = reviewKnowledgeGuidance.trim();
    if (normalizedTitle.length === 0 || normalizedGuidance.length === 0) {
      setError("Review knowledge title and guidance are required");
      return;
    }
    await run(async () => {
      await apiClient.createReviewKnowledge(
        session.id,
        normalizedTitle,
        normalizedGuidance,
        reviewKnowledgeScope.trim(),
      );
      setReviewKnowledgeTitle("");
      setReviewKnowledgeScope("");
      setReviewKnowledgeGuidance("");
    });
  }

  async function handleSessionInsightKnowledge(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedTitle = sessionInsightTitle.trim();
    const normalizedGuidance = sessionInsightGuidance.trim();
    if (normalizedTitle.length === 0 || normalizedGuidance.length === 0) {
      setError("Session insight title and guidance are required");
      return;
    }
    await run(async () => {
      await apiClient.createSessionInsightKnowledge(
        session.id,
        normalizedTitle,
        normalizedGuidance,
        sessionInsightScope.trim(),
      );
      setSessionInsightTitle("");
      setSessionInsightScope("");
      setSessionInsightGuidance("");
    });
  }

  const canOpenFollowup = session.status === "completed";
  const canCompleteSelfReview =
    session.current_stage === "self_review_requested" && session.status === "active";
  const canCompleteDocHarvest =
    (session.current_stage === "doc_harvest_requested" && session.status === "active") ||
    (session.current_stage === "completed" && session.status === "completed");
  const canStartSubtaskGraph =
    session.status === "active" &&
    session.workflow_profile === "story_full" &&
    session.current_stage === "implementation_requested";
  const canCreateMr = session.status === "completed" && session.current_stage !== "mr_handoff_completed";
  const canSendToTest =
    session.status === "completed" && session.current_stage === "mr_handoff_completed";

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Control</p>
          <h3>Operator Actions</h3>
        </div>
      </div>

      <div className="actions-grid">
        <button
          className="action-button"
          disabled={busy || session.status !== "active"}
          onClick={() => run(() => apiClient.pauseSession(session.id))}
          type="button"
        >
          Pause Session
        </button>
        <button
          className="action-button"
          disabled={busy || !["paused", "waiting_for_operator"].includes(session.status)}
          onClick={() => run(() => apiClient.resumeSession(session.id))}
          type="button"
        >
          Resume Session
        </button>
        <button
          className="action-button"
          disabled={busy || session.status !== "waiting_for_operator"}
          onClick={() => run(() => apiClient.retrySession(session.id))}
          type="button"
        >
          Retry Current Stage
        </button>
        <button
          className="action-button"
          disabled={busy}
          onClick={() => run(() => apiClient.runLoopOnce())}
          type="button"
        >
          Run Loop Once
        </button>
        <button
          className="action-button action-button-strong"
          disabled={busy || !canStartSubtaskGraph}
          onClick={() => run(() => apiClient.startSubtaskGraph(session.id))}
          type="button"
        >
          Start Subtask Graph
        </button>
        <button
          className="action-button action-button-strong"
          disabled={busy || !canCreateMr}
          onClick={() => run(() => apiClient.createMr(session.id))}
          type="button"
        >
          Create MR Handoff
        </button>
        <button
          className="action-button action-button-strong"
          disabled={busy || !canSendToTest}
          onClick={() => run(() => apiClient.sendToTest(session.id))}
          type="button"
        >
          Send To Test
        </button>
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
          <h4>Promote Review Feedback</h4>
          <p className="path-label">
            Capture a reusable repo-visible rule from merge request review feedback.
          </p>
        </div>

        <form className="followup-form" onSubmit={(event) => void handleReviewKnowledge(event)}>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Knowledge Title</span>
              <input
                className="text-input"
                disabled={busy}
                onChange={(event) => setReviewKnowledgeTitle(event.target.value)}
                placeholder="Reuse existing formatter helper"
                value={reviewKnowledgeTitle}
              />
            </label>
            <label className="form-field">
              <span>Scope</span>
              <input
                className="text-input"
                disabled={busy}
                onChange={(event) => setReviewKnowledgeScope(event.target.value)}
                placeholder="shared-formatting"
                value={reviewKnowledgeScope}
              />
            </label>
          </div>
          <label className="form-field">
            <span>Guidance</span>
            <textarea
              className="text-area-input"
              disabled={busy}
              onChange={(event) => setReviewKnowledgeGuidance(event.target.value)}
              placeholder="Do not introduce a new helper here; use the existing shared formatter already used in this module."
              rows={4}
              value={reviewKnowledgeGuidance}
            />
          </label>
          <button className="action-button" disabled={busy} type="submit">
            Create Review Knowledge
          </button>
        </form>
      </div>

      <div className="operator-followup-stack">
        <div className="operator-followup-copy">
          <p className="eyebrow">Knowledge</p>
          <h4>Capture Session Insight</h4>
          <p className="path-label">
            Record a non-obvious discovery from the current session so it becomes visible in later similar work.
          </p>
        </div>

        <form className="followup-form" onSubmit={(event) => void handleSessionInsightKnowledge(event)}>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Insight Title</span>
              <input
                className="text-input"
                disabled={busy}
                onChange={(event) => setSessionInsightTitle(event.target.value)}
                placeholder="State actually lives in presenter cache"
                value={sessionInsightTitle}
              />
            </label>
            <label className="form-field">
              <span>Scope</span>
              <input
                className="text-input"
                disabled={busy}
                onChange={(event) => setSessionInsightScope(event.target.value)}
                placeholder="card-details"
                value={sessionInsightScope}
              />
            </label>
          </div>
          <label className="form-field">
            <span>Guidance</span>
            <textarea
              className="text-area-input"
              disabled={busy}
              onChange={(event) => setSessionInsightGuidance(event.target.value)}
              placeholder="Treat the presenter cache as the real source of truth; direct VC state updates will drift."
              rows={4}
              value={sessionInsightGuidance}
            />
          </label>
          <button className="action-button" disabled={busy} type="submit">
            Create Session Insight
          </button>
        </form>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
