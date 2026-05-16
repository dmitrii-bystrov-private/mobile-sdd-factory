import type { SubtaskGraphSummary } from "../types";

type SubtaskGraphPanelProps = {
  subtaskGraphSummary: SubtaskGraphSummary | null;
};

function countTerminal(rows: SubtaskGraphSummary["rows"]): number {
  const terminalStatuses = new Set(["ready for test", "released", "resolved"]);
  return rows.filter((row) => terminalStatuses.has(row.status.trim().toLowerCase())).length;
}

export function SubtaskGraphPanel({
  subtaskGraphSummary,
}: SubtaskGraphPanelProps): JSX.Element | null {
  if (subtaskGraphSummary === null) {
    return null;
  }

  const completedCount = countTerminal(subtaskGraphSummary.rows);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Execution Graph</p>
          <h3>Subtask Graph</h3>
        </div>
        <span className="badge badge-muted">
          {completedCount}/{subtaskGraphSummary.rows.length}
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
