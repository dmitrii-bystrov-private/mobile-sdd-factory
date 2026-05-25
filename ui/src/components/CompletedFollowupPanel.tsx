import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import { useToast } from "./ToastProvider";
import type { Artifact, EventItem, Session } from "../types";

type CompletedFollowupPanelProps = {
  session: Session;
  artifacts: Artifact[];
  events: EventItem[];
  onRefresh: () => Promise<void>;
};

function inferPlatform(taskKey: string): "ios" | "android" {
  return taskKey.startsWith("ANDR-") ? "android" : "ios";
}

function latestMrUrl(artifacts: Artifact[], events: EventItem[]): string | null {
  for (const artifact of [...artifacts].reverse()) {
    const value = artifact.metadata?.mr_url;
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }
  for (const event of [...events].reverse()) {
    const value = event.payload?.mr_url;
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }
  return null;
}

function mrIdFromUrl(mrUrl: string | null): string {
  if (!mrUrl) {
    return "";
  }
  const match = mrUrl.match(/merge_requests\/(\d+)/);
  return match?.[1] ?? "";
}

export function CompletedFollowupPanel({
  session,
  artifacts,
  events,
  onRefresh,
}: CompletedFollowupPanelProps): JSX.Element | null {
  const { showToast, showActivity, clearActivity } = useToast();
  const mrUrl = useMemo(() => latestMrUrl(artifacts, events), [artifacts, events]);
  const inferredMrId = useMemo(() => mrIdFromUrl(mrUrl), [mrUrl]);
  const platform = inferPlatform(session.task_key);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);

  useEffect(() => {
    if (inferredMrId.length === 0) {
      setPreviewText(null);
      return undefined;
    }

    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      void (async () => {
        setPreviewLoading(true);
        try {
          const response = await apiClient.getReviewMessagePreview(session.id, inferredMrId);
          if (!cancelled) {
            setPreviewText(response.text);
          }
        } catch {
          if (!cancelled) {
            setPreviewText(null);
          }
        } finally {
          if (!cancelled) {
            setPreviewLoading(false);
          }
        }
      })();
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [inferredMrId, session.id]);

  async function run(action: () => Promise<void>, activityLabel?: string): Promise<void> {
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

  async function copyPreview(): Promise<void> {
    if (!previewText) {
      return;
    }
    try {
      await navigator.clipboard.writeText(previewText);
      showToast("Review message copied");
    } catch {
      showToast("Copy failed", "error");
    }
  }

  async function handleIngestMrComments(): Promise<void> {
    if (inferredMrId.length === 0) {
      setError("MR data is not available for this session yet");
      showToast("MR data is not available for this session yet", "error");
      return;
    }
    await run(async () => {
      await apiClient.ingestMrComments(session.id, platform, inferredMrId);
    }, "Processing MR comments…");
  }

  async function handleRefreshSnapshot(): Promise<void> {
    await run(async () => {
      await apiClient.refreshSnapshot(session.id);
    }, "Refreshing snapshot and resuming subtasks…");
  }

  if (session.status !== "completed") {
    return null;
  }

  return (
    <section className="panel completed-followup-panel">
      {mrUrl ? (
        <a className="hero-link hero-link-button completed-followup-link" href={mrUrl} rel="noreferrer" target="_blank">
          Open MR
        </a>
      ) : null}

      <div className="panel-header">
        <div>
          <p className="eyebrow">Follow-up</p>
          <h3>Completed Session Recovery</h3>
        </div>
      </div>

      <div className="completed-followup-stack">
        <div className="completed-followup-preview">
          <strong className="completed-followup-preview-title">Review Message</strong>
          <button
            aria-label="Copy review message"
            className="completed-followup-copy"
            disabled={!previewText}
            onClick={() => void copyPreview()}
            title="Copy review message"
            type="button"
          >
            <span className="completed-followup-copy-icon" aria-hidden="true">
              <span />
              <span />
            </span>
          </button>
          <pre className="completed-followup-preview-body">
            {previewLoading
              ? "Loading review message..."
              : previewText ?? "MR data is not available for this session yet."}
          </pre>
        </div>

        <div className="completed-followup-actions">
          <button
            className="action-button"
            disabled={busy || inferredMrId.length === 0}
            onClick={() => void handleIngestMrComments()}
            type="button"
          >
            Process MR comments
          </button>
          <button
            className="action-button"
            disabled={busy}
            onClick={() => void handleRefreshSnapshot()}
            type="button"
          >
            Refresh snapshot and resume subtasks
          </button>
        </div>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
