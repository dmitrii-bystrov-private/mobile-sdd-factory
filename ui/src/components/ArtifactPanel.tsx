import type { Artifact, EventItem } from "../types";
import { stageDisplayName } from "../stageDisplay";

const ARTIFACT_LABELS: Record<string, string> = {
  self_review_report_markdown: "Self Review Report",
  self_review_outcome_json: "Self Review Outcome",
  boy_scout_report_markdown: "Code Scout Report",
  boy_scout_outcome_json: "Code Scout Outcome",
  boy_scout_actionable_markdown: "Code Scout Actionable Findings",
  boy_scout_deferred_markdown: "Deferred Code Scout Findings",
  boy_scout_findings: "Code Scout Findings Source",
  final_verification_markdown: "Verification Report",
};

function humanizeEventType(value: string): string {
  return value
    .split("_")
    .filter((part) => part.length > 0)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function artifactDisplayName(value: string): string {
  return ARTIFACT_LABELS[value] ?? humanizeEventType(value);
}

function reviewLaneDisplayName(value: string): string {
  switch (value) {
    case "self_review":
      return "Self Review";
    case "code_scout":
      return "Code Scout";
    default:
      return humanizeEventType(value);
  }
}

function artifactContextLine(artifact: Artifact): string {
  const metadata = artifact.metadata ?? null;
  if (metadata && metadata["report_family"] === "internal_review") {
    const reviewLane = typeof metadata["review_lane"] === "string" ? metadata["review_lane"] : "";
    const artifactRole = typeof metadata["artifact_role"] === "string" ? metadata["artifact_role"] : "";
    const parts = ["Internal Review"];
    if (reviewLane) {
      parts.push(reviewLaneDisplayName(reviewLane));
    }
    if (artifactRole) {
      parts.push(humanizeEventType(artifactRole));
    }
    return parts.join(" · ");
  }
  return stageDisplayName(artifact.stage_name);
}

function producerDisplayName(value: string): string {
  if (value === "coordinator") {
    return "Coordinator";
  }
  if (value === "role") {
    return "Role Runtime";
  }
  if (value === "operator") {
    return "Operator";
  }
  return humanizeEventType(value);
}

type ArtifactPanelProps = {
  artifacts: Artifact[];
  events: EventItem[];
};

export function ArtifactPanel({
  artifacts,
  events,
}: ArtifactPanelProps): JSX.Element {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Debug</p>
          <h3>Artifacts And Event Log</h3>
        </div>
      </div>

      <div className="grid-two runtime-log-grid">
        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Generated Files</strong>
            <span className="badge badge-muted">{artifacts.length}</span>
          </div>
          <div className="table-list limited-list">
            {artifacts.map((artifact) => (
              <div className="table-row" key={artifact.id}>
                <div>
                  <strong>{artifactDisplayName(artifact.artifact_type)}</strong>
                  <p>{artifactContextLine(artifact)}</p>
                </div>
                <small className="path-label">{artifact.path}</small>
              </div>
            ))}
          </div>
        </div>

        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Event Log</strong>
            <span className="badge badge-muted">{events.length}</span>
          </div>
          <div className="table-list limited-list">
            {events.map((event) => (
              <div className="table-row" key={event.id}>
                <div>
                  <strong>{humanizeEventType(event.event_type)}</strong>
                  <p>From {producerDisplayName(event.producer_type)}</p>
                </div>
                <small>Event {event.id}</small>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
