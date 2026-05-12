import type { Artifact, EventItem } from "../types";

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
          <p className="eyebrow">Trace</p>
          <h3>Artifacts And Events</h3>
        </div>
      </div>

      <div className="grid-two">
        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Artifacts</strong>
            <span className="badge badge-muted">{artifacts.length}</span>
          </div>
          <div className="table-list limited-list">
            {artifacts.map((artifact) => (
              <div className="table-row" key={artifact.id}>
                <div>
                  <strong>{artifact.artifact_type}</strong>
                  <p>{artifact.stage_name}</p>
                </div>
                <small className="path-label">{artifact.path}</small>
              </div>
            ))}
          </div>
        </div>

        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Recent Events</strong>
            <span className="badge badge-muted">{events.length}</span>
          </div>
          <div className="table-list limited-list">
            {events.map((event) => (
              <div className="table-row" key={event.id}>
                <div>
                  <strong>{event.event_type}</strong>
                  <p>{event.producer_type}</p>
                </div>
                <small>#{event.id}</small>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
