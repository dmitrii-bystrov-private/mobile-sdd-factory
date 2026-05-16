import type {
  JiraSubtasksSummary,
  SubtaskGraphSummary,
  SubtaskProgressSummary,
} from "../types";

type JiraSubtasksPanelProps = {
  jiraSubtasksSummary: JiraSubtasksSummary | null;
  subtaskGraphSummary: SubtaskGraphSummary | null;
  subtaskProgressSummary: SubtaskProgressSummary | null;
};

export function JiraSubtasksPanel({
  jiraSubtasksSummary,
  subtaskGraphSummary,
  subtaskProgressSummary,
}: JiraSubtasksPanelProps): JSX.Element | null {
  if (jiraSubtasksSummary === null) {
    return null;
  }

  const graphRowsByKey = new Map(
    (subtaskGraphSummary?.rows ?? []).map((row) => [row.key, row]),
  );
  const progressItemsByKey = new Map(
    (subtaskProgressSummary?.items ?? [])
      .filter((item) => item.key !== null)
      .map((item) => [item.key as string, item]),
  );

  return (
    <section className="subpanel">
      <div className="subpanel-head">
        <strong>Jira Subtasks</strong>
      </div>
      {jiraSubtasksSummary.items.length > 0 ? (
        <div className="table-list">
          {jiraSubtasksSummary.items.map((item) => {
            const graphRow = graphRowsByKey.get(item.key);
            const progressItem = progressItemsByKey.get(item.key);
            const isCurrent = item.isCurrent || subtaskProgressSummary?.currentSubtaskKey === item.key;

            return (
              <div className="table-row" key={item.key}>
                <div>
                  <strong>{item.key}</strong>
                  <p>{graphRow?.title ?? item.title ?? item.key}</p>
                </div>
                <div className="subtask-graph-meta">
                  {progressItem !== undefined || item.queuePosition !== null ? (
                    <small>#{progressItem?.queuePosition ?? item.queuePosition}</small>
                  ) : null}
                  {isCurrent ? <small>current</small> : null}
                  <strong>{graphRow?.status ?? item.status ?? "created"}</strong>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p>Subtask creation summary is available, but no keys were parsed.</p>
      )}
    </section>
  );
}
