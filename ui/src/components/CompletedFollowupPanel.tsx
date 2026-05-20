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
  const { showToast } = useToast();
  const inferredMrId = useMemo(() => mrIdFromUrl(latestMrUrl(artifacts, events)), [artifacts, events]);
  const platform = inferPlatform(session.task_key);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mrId, setMrId] = useState(inferredMrId);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);

  useEffect(() => {
    setMrId((current) => (current.trim().length === 0 ? inferredMrId : current));
  }, [inferredMrId]);

  useEffect(() => {
    const normalizedMrId = mrId.trim();
    if (normalizedMrId.length === 0) {
      setPreviewText(null);
      return undefined;
    }

    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      void (async () => {
        setPreviewLoading(true);
        try {
          const response = await apiClient.getReviewMessagePreview(session.id, normalizedMrId);
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
  }, [mrId, session.id]);

  async function run(action: () => Promise<void>): Promise<void> {
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
    const normalizedMrId = mrId.trim();
    if (normalizedMrId.length === 0) {
      setError("MR id is required");
      return;
    }
    await run(async () => {
      await apiClient.ingestMrComments(session.id, platform, normalizedMrId);
    });
  }

  async function handleRefreshSnapshot(): Promise<void> {
    await run(async () => {
      await apiClient.refreshSnapshot(session.id);
    });
  }

  if (session.status !== "completed") {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Follow-up</p>
          <h3>Completed Session Recovery</h3>
        </div>
      </div>

      <div className="completed-followup-stack">
        <label className="form-field">
          <span>MR Id</span>
          <input
            className="text-input"
            disabled={busy}
            onChange={(event) => setMrId(event.target.value)}
            placeholder="2942"
            value={mrId}
          />
        </label>

        <div className="completed-followup-actions">
          <button
            className="action-button"
            disabled={busy || mrId.trim().length === 0}
            onClick={() => void handleIngestMrComments()}
            type="button"
          >
            Process MR Comments
          </button>
          <button
            className="action-button"
            disabled={busy}
            onClick={() => void handleRefreshSnapshot()}
            type="button"
          >
            Refresh Snapshot And Resume Subtasks
          </button>
        </div>

        <div className="completed-followup-preview">
          <div className="completed-followup-preview-head">
            <strong>Review Message</strong>
            <button
              className="action-button action-button-ghost"
              disabled={!previewText}
              onClick={() => void copyPreview()}
              type="button"
            >
              Copy
            </button>
          </div>
          <pre className="completed-followup-preview-body">
            {previewLoading
              ? "Loading review message..."
              : previewText ?? "Enter MR id to preview the review message."}
          </pre>
        </div>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
