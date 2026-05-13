import type { FollowupContext } from "../types";

type FollowupContextPanelProps = {
  followupContext: FollowupContext | null;
};

function summarizeContent(content: string | null | undefined): string {
  if (typeof content !== "string") {
    return "No captured follow-up content.";
  }
  const normalized = content.replace(/\s+/g, " ").trim();
  if (normalized.length === 0) {
    return "No captured follow-up content.";
  }
  return normalized.length > 220 ? `${normalized.slice(0, 217)}...` : normalized;
}

export function FollowupContextPanel({
  followupContext,
}: FollowupContextPanelProps): JSX.Element {
  if (followupContext === null) {
    return (
      <section className="subpanel">
        <div className="subpanel-head">
          <strong>Follow-up Context</strong>
        </div>
        <p className="followup-empty">
          This session has not been reopened from MR or QA feedback yet.
        </p>
      </section>
    );
  }

  const sourceLabel =
    followupContext.source === "mr" ? "Merge Request Feedback" : "QA Reopen";

  return (
    <section className="subpanel">
      <div className="subpanel-head">
        <strong>Follow-up Context</strong>
        <span className="badge badge-muted">{sourceLabel}</span>
      </div>

      <div className="table-list">
        <div className="table-row">
          <span>Source Event</span>
          <strong>{followupContext.eventType}</strong>
        </div>
        <div className="table-row">
          <span>Follow-up Stage</span>
          <strong>{followupContext.stageName}</strong>
        </div>
        <div className="table-row">
          <span>Trace</span>
          <strong>#{followupContext.eventId}</strong>
        </div>
        <div className="table-row">
          <span>Artifact</span>
          <strong>{followupContext.artifactType}</strong>
        </div>
        {Object.entries(followupContext.eventPayload).map(([key, value]) => (
          <div className="table-row" key={key}>
            <span>{key}</span>
            <strong>{String(value)}</strong>
          </div>
        ))}
      </div>

      <div className="followup-snippet">
        <span className="followup-snippet-label">Latest Captured Context</span>
        <p>{summarizeContent(followupContext.artifactDetail?.content)}</p>
      </div>
    </section>
  );
}
