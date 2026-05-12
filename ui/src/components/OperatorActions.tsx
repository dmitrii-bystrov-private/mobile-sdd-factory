import { useState } from "react";

import { apiClient } from "../api/client";
import type { Role, Session } from "../types";

type OperatorActionsProps = {
  session: Session;
  roles: Role[];
  onRefresh: () => Promise<void>;
};

export function OperatorActions({
  session,
  roles,
  onRefresh,
}: OperatorActionsProps): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [redirectTarget, setRedirectTarget] = useState<string>("");

  const roleTargets = roles
    .map((role) => role.role_name)
    .filter((roleName) => roleName !== session.current_owner);

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
      </div>

      <div className="redirect-box">
        <select
          className="select-input"
          onChange={(event) => setRedirectTarget(event.target.value)}
          value={redirectTarget}
        >
          <option value="">Select redirect target</option>
          {roleTargets.map((roleName) => (
            <option key={roleName} value={roleName}>
              {roleName}
            </option>
          ))}
        </select>
        <button
          className="action-button action-button-strong"
          disabled={busy || session.status !== "waiting_for_operator" || redirectTarget === ""}
          onClick={() =>
            run(() => apiClient.redirectSession(session.id, redirectTarget))
          }
          type="button"
        >
          Redirect Escalated Session
        </button>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
