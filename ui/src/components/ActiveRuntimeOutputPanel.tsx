import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import { roleDisplayName } from "../roleDisplay";

type ActiveRuntimeOutputPanelProps = {
  sessionId: number;
  runtimeAvailable: boolean;
};

export function ActiveRuntimeOutputPanel({
  sessionId,
  runtimeAvailable,
}: ActiveRuntimeOutputPanelProps): JSX.Element | null {
  const [loading, setLoading] = useState(false);
  const [activeOutput, setActiveOutput] = useState<{
    available: boolean;
    roleName: string | null;
    content: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadActiveOutput(): Promise<void> {
      if (!runtimeAvailable) {
        setActiveOutput(null);
        return;
      }
      setLoading(true);
      try {
        const response = await apiClient.getActiveRuntimeOutput(sessionId);
        if (cancelled) {
          return;
        }
        setActiveOutput({
          available: response.available,
          roleName: response.role_name,
          content: response.content,
        });
      } catch {
        if (!cancelled) {
          setActiveOutput(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadActiveOutput();
    return () => {
      cancelled = true;
    };
  }, [runtimeAvailable, sessionId]);

  if (!runtimeAvailable) {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Live Output</p>
          <h3>Active Worker Console</h3>
        </div>
        {activeOutput?.roleName ? (
          <span className="badge badge-muted">{roleDisplayName(activeOutput.roleName)}</span>
        ) : null}
      </div>

      {loading ? (
        <p className="path-label">Loading active worker output…</p>
      ) : activeOutput?.available && activeOutput.content.trim().length > 0 ? (
        <pre className="runtime-output-content">{activeOutput.content}</pre>
      ) : (
        <p className="path-label">No active worker console output is available right now.</p>
      )}
    </section>
  );
}
