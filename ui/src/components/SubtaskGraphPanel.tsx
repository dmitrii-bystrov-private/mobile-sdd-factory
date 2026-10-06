import type { SubtaskGraphSummary } from "../types";

type SubtaskGraphPanelProps = {
  subtaskGraphSummary: SubtaskGraphSummary | null;
};

export function SubtaskGraphPanel({
  subtaskGraphSummary,
}: SubtaskGraphPanelProps): JSX.Element | null {
  if (subtaskGraphSummary === null || !subtaskGraphSummary.available) {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Execution Graph</p>
          <h3>Subtask Graph</h3>
        </div>
        <span className="badge badge-muted">
          {subtaskGraphSummary.completedCount}/{subtaskGraphSummary.totalCount}
        </span>
      </div>

      <div className="table-list limited-list">
        {subtaskGraphSummary.rows.map((row) => (
          <div className="table-row" key={row.key}>
            <div>
              <strong>{row.key}</strong>
              <p>{row.title}</p>
            </div>
            <div className="subtask-graph-meta">
              <small>{row.issueType}</small>
              <strong>{row.status}</strong>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
