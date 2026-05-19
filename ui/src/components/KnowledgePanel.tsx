import type { KnowledgeItem } from "../types";

type KnowledgePanelProps = {
  items: KnowledgeItem[];
};

export function KnowledgePanel({ items }: KnowledgePanelProps): JSX.Element {
  if (items.length === 0) {
    return (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Knowledge</p>
            <h3>Shared Knowledge</h3>
          </div>
        </div>
        <div className="inline-summary-card">
          <div className="inline-summary-header">
            <strong>No captured knowledge yet</strong>
            <span>empty</span>
          </div>
          <p className="form-help">
            Reusable project conventions and findings will appear here after operators capture them from real sessions.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Knowledge</p>
          <h3>Shared Knowledge</h3>
          <p className="path-label">
            Reusable conventions, constraints, and implementation notes captured from previous runs.
          </p>
        </div>
      </div>

      <div className="table-list limited-list">
        {items.map((item) => (
          <div className="knowledge-card" key={item.path}>
            <div className="knowledge-card-head">
              <strong>{item.title}</strong>
            </div>
            <div className="inline-pill-row">
              <span className="inline-pill">{item.scope ?? "general"}</span>
              <span className="inline-pill">{item.platform}</span>
              <span className="inline-pill">{item.workflow_profiles.join(", ")}</span>
            </div>
            <p>{item.guidance}</p>
            <small className="path-label">{item.path}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
