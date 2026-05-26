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

  if (interactiveStateSummary === null || !interactiveStateSummary.available) {
    return null;
  }

  if (
    !interactiveStateSummary.needsOperatorInput &&
    interactiveStateSummary.sourceReason === "boy_scout_findings"
  ) {
    return null;
  }

  const questionText = interactiveStateSummary.details ?? interactiveStateSummary.summary;
  const isProtocolViolation = interactiveStateSummary.sourceReason === "role_result_protocol_violation";
  const blockingRoleName = interactiveStateSummary.roleName;
  const blockingRole =
    blockingRoleName !== null
      ? runtimeStateSummary?.roles.find((role) => role.roleName === blockingRoleName) ?? null
      : null;
  const title = interactiveStateSummary.needsOperatorInput
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
        {questionText ? (
          <div className="interactive-question-card">
            <p>{questionText}</p>
          </div>
        ) : null}
      </div>

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
              placeholder="Reply to the worker here."
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
            Send reply
          </button>
        </form>
      ) : null}

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
