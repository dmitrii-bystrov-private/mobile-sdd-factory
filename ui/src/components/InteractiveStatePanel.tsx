import { useState } from "react";

import { apiClient } from "../api/client";
import { roleDisplayName } from "../roleDisplay";
import type { InteractiveStateSummary } from "../types";

type InteractiveStatePanelProps = {
  sessionId: number;
  interactiveStateSummary: InteractiveStateSummary | null;
  onRefresh: () => Promise<void>;
};

export function InteractiveStatePanel({
  sessionId,
  interactiveStateSummary,
  onRefresh,
}: InteractiveStatePanelProps): JSX.Element | null {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeInput, setRuntimeInput] = useState("");

  if (
    interactiveStateSummary === null ||
    !interactiveStateSummary.available ||
    !interactiveStateSummary.needsOperatorInput
  ) {
    return null;
  }

  const questionText = interactiveStateSummary.details ?? interactiveStateSummary.summary;

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
          <h3>{roleDisplayName(interactiveStateSummary.roleName)} needs a reply</h3>
        </div>
      </div>

      <div className="interactive-question-stack">
        {questionText ? (
          <div className="interactive-question-card">
            <p>{questionText}</p>
          </div>
        ) : null}
      </div>

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
          Send Reply
        </button>
      </form>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
