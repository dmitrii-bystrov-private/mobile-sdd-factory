import type { KnowledgeItem } from "../types";

type KnowledgePanelProps = {
  items: KnowledgeItem[];
};

export function KnowledgePanel({ items }: KnowledgePanelProps): JSX.Element {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Knowledge</p>
          <h3>Shared Knowledge</h3>
        </div>
      </div>

      <div className="table-list limited-list">
        {items.map((item) => (
          <div className="knowledge-card" key={item.path}>
            <div className="knowledge-card-head">
              <strong>{item.title}</strong>
              <span className="badge badge-muted">{item.source_type}</span>
            </div>
            <p className="path-label">
              {item.platform} · {item.workflow_profiles.join(", ")} · {item.scope ?? "global"}
            </p>
            <p>{item.guidance}</p>
            <small className="path-label">{item.path}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
