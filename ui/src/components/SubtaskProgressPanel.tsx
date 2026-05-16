import type { SubtaskProgressSummary } from "../types";

type SubtaskProgressPanelProps = {
  subtaskProgressSummary: SubtaskProgressSummary | null;
};

export function SubtaskProgressPanel({
  subtaskProgressSummary,
}: SubtaskProgressPanelProps): JSX.Element | null {
  if (subtaskProgressSummary === null || !subtaskProgressSummary.available) {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Execution Queue</p>
          <h3>Subtask Progress</h3>
        </div>
        <span className="badge badge-muted">
          {subtaskProgressSummary.completedCount}/{subtaskProgressSummary.totalCount}
        </span>
      </div>

      <div className="grid-two">
        <article className="subpanel">
          <div className="subpanel-head">
            <strong>Current</strong>
            <span className="badge badge-muted">{subtaskProgressSummary.remainingCount} remaining</span>
          </div>
          {subtaskProgressSummary.currentSubtaskKey !== null ? (
            <div className="stack-tight">
              <strong>{subtaskProgressSummary.currentSubtaskKey}</strong>
              <p>{subtaskProgressSummary.currentSubtaskTitle}</p>
            </div>
          ) : (
            <p>No active subtask is currently assigned.</p>
          )}
        </article>

        <article className="subpanel">
          <div className="subpanel-head">
            <strong>Queue</strong>
            <span className="badge badge-muted">{subtaskProgressSummary.items.length}</span>
          </div>
          <div className="table-list limited-list">
            {subtaskProgressSummary.items.map((item) => (
              <div className="table-row" key={item.workItemId}>
                <div>
                  <strong>{item.key ?? `Work Item ${item.workItemId}`}</strong>
                  <p>{item.title}</p>
                </div>
                <div className="subtask-graph-meta">
                  <small>#{item.queuePosition}</small>
                  <span className={`status-pill status-${item.status}`}>{item.status}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
