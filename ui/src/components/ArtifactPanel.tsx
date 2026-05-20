import type { Artifact, EventItem } from "../types";
import { stageDisplayName } from "../stageDisplay";

function humanizeEventType(value: string): string {
  return value
    .split("_")
    .filter((part) => part.length > 0)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
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
                  <strong>{humanizeEventType(artifact.artifact_type)}</strong>
                  <p>{stageDisplayName(artifact.stage_name)}</p>
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
