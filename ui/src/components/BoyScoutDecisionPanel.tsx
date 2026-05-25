import { useState } from "react";

import { apiClient } from "../api/client";
import type { InteractiveStateSummary, Session } from "../types";
import { useToast } from "./ToastProvider";

type BoyScoutDecisionPanelProps = {
  session: Session;
  interactiveStateSummary: InteractiveStateSummary | null;
  onRefresh: () => Promise<void>;
};

export function BoyScoutDecisionPanel({
  session,
  interactiveStateSummary,
  onRefresh,
}: BoyScoutDecisionPanelProps): JSX.Element | null {
  const { showActivity, clearActivity, showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipReason, setSkipReason] = useState("");

  const canSkip =
    session.current_stage === "boy_scout_requested" &&
    session.status === "waiting_for_operator" &&
    interactiveStateSummary?.sourceReason === "boy_scout_findings" &&
    session.policy["boy_scout_policy"] === "enabled";
  const canResolve =
    session.current_stage === "boy_scout_requested" &&
    session.status === "waiting_for_operator" &&
    interactiveStateSummary?.sourceReason === "boy_scout_findings";

  if (!canSkip && !canResolve) {
    return null;
  }

  const details = interactiveStateSummary?.details?.trim() ?? "";

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

  async function handleResolution(resolution: "implement_now" | "create_tech_debt"): Promise<void> {
    await run(() => apiClient.resolveBoyScoutFindings(session.id, resolution));
  }

  async function handleSkip(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedReason = skipReason.trim();
    if (normalizedReason.length === 0) {
      setError("Boy Scout skip reason is required");
      return;
    }
    await run(async () => {
      await apiClient.skipBoyScout(session.id, normalizedReason);
      setSkipReason("");
    });
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Waiting for Operator</p>
          <h3>Boy Scout Decision</h3>
        </div>
      </div>

      <div className="operator-followup-stack">
        {details ? (
          <div className="interactive-question-stack">
            <div className="interactive-question-card">
              <p className="interactive-question-text-prewrap">{details}</p>
            </div>
          </div>
        ) : null}

        {canResolve ? (
          <div className="operator-actions-toolbar operator-actions-toolbar-horizontal">
            <button
              className="action-button"
              disabled={busy}
              onClick={() => void handleResolution("implement_now")}
              title="Send every Boy Scout finding back to the coding lane immediately."
              type="button"
            >
              Implement Boy Scout findings
            </button>
            <button
              className="action-button"
              disabled={busy}
              onClick={() => void handleResolution("create_tech_debt")}
              title="Create tech-debt stories for the old-code findings and route the remaining actionable findings back to the coder."
              type="button"
            >
              Create tech debt and continue
            </button>
          </div>
        ) : null}

        {canSkip ? (
          <form className="followup-form followup-form-plain" onSubmit={(event) => void handleSkip(event)}>
            <label className="form-field">
              <span>Skip reason</span>
              <textarea
                className="text-area-input"
                disabled={busy}
                onChange={(event) => setSkipReason(event.target.value)}
                placeholder="Example: Findings acknowledged; continue with final verification and track refactors separately."
                rows={3}
                value={skipReason}
              />
            </label>
            <button
              className="action-button"
              disabled={busy}
              title="Skip the optional Boy Scout lane for this session and continue with the downstream flow."
              type="submit"
            >
              Skip Boy Scout lane
            </button>
          </form>
        ) : null}
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
