import { useState } from "react";

import { apiClient } from "../api/client";
import { useToast } from "./ToastProvider";
import { roleDisplayName } from "../roleDisplay";
import type { InteractiveStateSummary, RuntimeSessionStateSummary } from "../types";

type InteractiveStatePanelProps = {
  sessionId: number;
  interactiveStateSummary: InteractiveStateSummary | null;
  runtimeStateSummary: RuntimeSessionStateSummary | null;
  onRefresh: () => Promise<void>;
};

function renderStructuredText(text: string, className: string): JSX.Element[] {
  return text
    .split(/\n\s*\n/)
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk.length > 0)
    .map((chunk, index) => (
      <p key={`${className}-${index}`} className={className}>
        {chunk}
      </p>
    ));
}

export function InteractiveStatePanel({
  sessionId,
  interactiveStateSummary,
  runtimeStateSummary,
  onRefresh,
}: InteractiveStatePanelProps): JSX.Element | null {
  const { showActivity, clearActivity, showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeInput, setRuntimeInput] = useState("");
  const [baselineSelection, setBaselineSelection] = useState<{ gate: string; ids: string[] } | null>(null);
  const [baselineCommentState, setBaselineComment] = useState<{ gate: string; text: string } | null>(null);

  if (interactiveStateSummary === null || !interactiveStateSummary.available) {
    return null;
  }

  const isE2EEnvironmentRecovery = interactiveStateSummary.sourceReason === "e2e_environment";
  const baselineDecision = interactiveStateSummary.e2eDecision;
  const selectedFindings = baselineSelection?.gate === baselineDecision?.verdict_digest ? baselineSelection?.ids ?? [] : [];
  const baselineComment = baselineCommentState?.gate === baselineDecision?.verdict_digest ? baselineCommentState?.text ?? "" : "";
  const rawDetails = interactiveStateSummary.details?.trim() ?? "";
  const isLegacyBaselineDetails = isE2EEnvironmentRecovery && rawDetails.startsWith("[{") &&
    rawDetails.includes("baseline_or_environment_failure");
  const legacyTest = isLegacyBaselineDetails
    ? rawDetails.match(/["']test["']\s*:\s*["']([^"']+)["']/)?.[1]?.split("::").pop()
    : undefined;
  const summaryText = isLegacyBaselineDetails
    ? "A selected test also fails on baseline."
    : interactiveStateSummary.summary?.trim() ?? "";
  const detailsText = isLegacyBaselineDetails
    ? `${legacyTest ?? "The selected scenario"} fails on the task branch and on baseline using the same app build. A regression caused by this task has not been established. See the verification report for the individual errors.`
    : rawDetails;
  const suppressSummaryForCycleBlocker =
    interactiveStateSummary.reviewFamily === "internal_review" &&
    Boolean(interactiveStateSummary.reviewLane) &&
    detailsText.length > 0;
  const showSummary = summaryText.length > 0 && !suppressSummaryForCycleBlocker;
  const showDetails = detailsText.length > 0 && detailsText !== summaryText;
  const isProtocolViolation = interactiveStateSummary.sourceReason === "role_result_protocol_violation";
  const blockingRoleName = interactiveStateSummary.roleName;
  const blockingRole =
    blockingRoleName !== null
      ? runtimeStateSummary?.roles.find((role) => role.roleName === blockingRoleName) ?? null
      : null;
  const title = isE2EEnvironmentRecovery
    ? "E2E verification is blocked"
    : interactiveStateSummary.needsOperatorInput
      ? `${roleDisplayName(interactiveStateSummary.roleName)} needs a reply`
      : isProtocolViolation
        ? `${roleDisplayName(interactiveStateSummary.roleName)} needs recovery`
        : interactiveStateSummary.roleName
          ? `${roleDisplayName(interactiveStateSummary.roleName)} needs a decision`
          : "Operator decision required";

  async function runRecoveryAction(
    action: () => Promise<unknown>,
    activityLabel: string,
  ): Promise<void> {
    setBusy(true);
    setError(null);
    showActivity(activityLabel);
    try {
      await action();
      await onRefresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown request error";
      setError(message);
      showToast(message, "error");
    } finally {
      clearActivity();
      setBusy(false);
    }
  }

  async function handleRuntimeInput(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedInput = runtimeInput.trim();
    if (normalizedInput.length === 0) {
      setError("Runtime input is required");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await apiClient.sendRuntimeInput(sessionId, normalizedInput);
      setRuntimeInput("");
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
          <p className="eyebrow">Waiting for Operator</p>
          <h3>{title}</h3>
        </div>
      </div>

      <div className="interactive-question-stack">
        {showSummary || showDetails ? (
          <div className="interactive-question-card">
            {showSummary ? renderStructuredText(summaryText, "interactive-question-summary") : null}
            {showDetails ? renderStructuredText(detailsText, "interactive-question-details") : null}
          </div>
        ) : null}
      </div>

      {isE2EEnvironmentRecovery ? (
        <div className="interactive-recovery-footer">
          <p className="form-help">{baselineDecision
            ? "These tests also fail on baseline. Review the errors, then accept specific findings for this verification or request corrections. Remaining checks will still run."
            : interactiveStateSummary.e2eContinuationAvailable
              ? "Resolve the reported blocker, then retry the continuation. Your accepted findings remain recorded for this verification."
              : "Resolve the reported blocker, then retry verification."}</p>
          {baselineDecision ? (
            <div className="e2e-baseline-decision">
              {baselineDecision.findings.map((finding) => (
                <label className="e2e-baseline-choice" key={finding.id}>
                  <input type="checkbox" disabled={busy} checked={selectedFindings.includes(finding.id)}
                    onChange={(event) => setBaselineSelection({ gate: baselineDecision.verdict_digest,
                      ids: event.target.checked ? [...selectedFindings, finding.id] : selectedFindings.filter((id) => id !== finding.id) })} />
                  <span>{finding.platform === "ios" ? "iOS" : "Android"}: {finding.test.split("::").pop()}</span>
                </label>
              ))}
              <label className="form-field">
                <span>Comment or linked issue (optional)</span>
                <textarea className="text-area-input" rows={2} maxLength={2000} disabled={busy}
                  value={baselineComment} onChange={(event) => setBaselineComment({ gate: baselineDecision.verdict_digest, text: event.target.value })}
                  placeholder="Known issue, tracked in QA-…" />
              </label>
              <p className="form-help">Accepted failures stay in the verification report and MR. This decision applies only to this verification.</p>
            </div>
          ) : null}
          <div className="operator-actions-toolbar">
            {interactiveStateSummary.e2eContinuationAvailable && !baselineDecision ? (
              <button className="action-button" type="button" disabled={busy}
                onClick={() => { void runRecoveryAction(() => apiClient.resumeSession(sessionId), "Retrying E2E continuation…"); }}>
                Retry continuation
              </button>
            ) : null}
            {baselineDecision ? (
              <>
                <button className="action-button" type="button" disabled={busy || selectedFindings.length === 0}
                  onClick={() => { void runRecoveryAction(
                    () => apiClient.resolveE2EBaseline(sessionId, baselineDecision, "accept", selectedFindings, baselineComment),
                    "Accepting baseline findings and continuing verification…"); }}>
                  Continue with findings
                </button>
                <button className="action-button" type="button" disabled={busy}
                  onClick={() => { void runRecoveryAction(
                    () => apiClient.resolveE2EBaseline(sessionId, baselineDecision, "correct", [], baselineComment),
                    "Requesting test corrections…"); }}>
                  Request corrections
                </button>
              </>
            ) : null}
            <button
              className="action-button"
              disabled={busy}
              onClick={() => {
                void runRecoveryAction(
                  () => apiClient.retrySession(sessionId),
                  "Retrying E2E verification…",
                );
              }}
              title="Run a new verification gate. Previously accepted findings do not carry over."
              type="button"
            >
              Retry verification
            </button>
          </div>
        </div>
      ) : null}

      {isProtocolViolation ? (
        <div className="operator-actions-toolbar interactive-recovery-toolbar">
          <button
            className="action-button"
            disabled={busy}
            onClick={() => {
              void runRecoveryAction(
                () => apiClient.retrySession(sessionId),
                "Requesting RESULT.json rewrite…",
              );
            }}
            title="Ask the same role to rewrite only the terminal RESULT.json for the current work item."
            type="button"
          >
            Ask role to rewrite RESULT.json
          </button>
          <button
            className="action-button"
            disabled={busy || blockingRole === null}
            onClick={() => {
              if (blockingRoleName === null) {
                return;
              }
              void runRecoveryAction(
                () => apiClient.restartRuntimeRole(sessionId, blockingRoleName),
                "Restarting runtime and redispatching…",
              );
            }}
            title="Restart the blocked runtime and redispatch the current work item."
            type="button"
          >
            Restart runtime and redispatch
          </button>
        </div>
      ) : null}

      {interactiveStateSummary.needsOperatorInput ? (
        <form className="followup-form interactive-reply-form interactive-reply-form-plain" onSubmit={(event) => void handleRuntimeInput(event)}>
          <label className="form-field">
            <textarea
              className="text-area-input"
              disabled={busy}
              onChange={(event) => setRuntimeInput(event.target.value)}
              placeholder="Send an authoritative operator reply here."
              rows={3}
              value={runtimeInput}
            />
          </label>
          <button
            className="action-button"
            disabled={busy}
            title="Send a direct reply into the live runtime session."
            type="submit"
          >
            Send operator reply
          </button>
        </form>
      ) : null}

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
