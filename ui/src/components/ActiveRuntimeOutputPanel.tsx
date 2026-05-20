import { useEffect, useRef, useState } from "react";

import { apiClient } from "../api/client";
import { roleDisplayName } from "../roleDisplay";

type ActiveRuntimeOutputPanelProps = {
  sessionId: number;
  runtimeAvailable: boolean;
};

function trimPromptTail(content: string): string {
  const lines = content.split("\n");
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    if (/^\s*[❯›»>]\s/.test(lines[index])) {
      return lines.slice(0, index).join("\n");
    }
  }
  return content;
}

export function ActiveRuntimeOutputPanel({
  sessionId,
  runtimeAvailable,
}: ActiveRuntimeOutputPanelProps): JSX.Element | null {
  const [loading, setLoading] = useState(false);
  const [followOutput, setFollowOutput] = useState(true);
  const [activeOutput, setActiveOutput] = useState<{
    available: boolean;
    roleName: string | null;
    content: string;
  } | null>(null);
  const outputRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    setFollowOutput(true);
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    async function loadActiveOutput(showLoading = false): Promise<void> {
      if (!runtimeAvailable) {
        setActiveOutput(null);
        return;
      }
      if (showLoading) {
        setLoading(true);
      }
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
        if (!cancelled && showLoading) {
          setLoading(false);
        }
      }
    }

    void loadActiveOutput(true);
    intervalId = setInterval(() => {
      void loadActiveOutput(false);
    }, 1000);

    return () => {
      cancelled = true;
      if (intervalId !== null) {
        clearInterval(intervalId);
      }
    };
  }, [runtimeAvailable, sessionId]);

  useEffect(() => {
    if (!followOutput) {
      return;
    }
    const element = outputRef.current;
    if (element === null) {
      return;
    }
    element.scrollTop = element.scrollHeight;
  }, [activeOutput?.content, followOutput]);

  function handleOutputScroll(): void {
    const element = outputRef.current;
    if (element === null) {
      return;
    }
    const distanceFromBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    setFollowOutput(distanceFromBottom <= 24);
  }

  const visibleContent = activeOutput ? trimPromptTail(activeOutput.content) : "";

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
      ) : activeOutput?.available && visibleContent.trim().length > 0 ? (
        <pre
          className="runtime-output-content"
          onScroll={handleOutputScroll}
          ref={outputRef}
        >
          {visibleContent}
        </pre>
      ) : (
        <p className="path-label">No active worker console output is available right now.</p>
      )}
    </section>
  );
}
