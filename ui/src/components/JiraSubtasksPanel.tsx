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

type ParsedSubtaskLine = {
  key: string;
  raw: string;
};

function parseSubtaskLines(content: string | null | undefined): ParsedSubtaskLine[] {
  if (content === null || content === undefined) {
    return [];
  }
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "))
    .map((line) => {
      const raw = line.slice(2).trim();
      const key = raw.split(/\s+/, 1)[0] ?? raw;
      return { key, raw };
    });
}

export function JiraSubtasksPanel({
  jiraSubtasksSummary,
  subtaskGraphSummary,
  subtaskProgressSummary,
}: JiraSubtasksPanelProps): JSX.Element | null {
  if (jiraSubtasksSummary === null) {
    return null;
  }

  const lines = parseSubtaskLines(jiraSubtasksSummary.artifactDetail?.content);
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
      {lines.length > 0 ? (
        <div className="table-list">
          {lines.map((line) => {
            const graphRow = graphRowsByKey.get(line.key);
            const progressItem = progressItemsByKey.get(line.key);
            const isCurrent = subtaskProgressSummary?.currentSubtaskKey === line.key;

            return (
              <div className="table-row" key={line.raw}>
                <div>
                  <strong>{line.key}</strong>
                  <p>{graphRow?.title ?? line.raw}</p>
                </div>
                <div className="subtask-graph-meta">
                  {progressItem !== undefined ? (
                    <small>#{progressItem.queuePosition}</small>
                  ) : null}
                  {isCurrent ? <small>current</small> : null}
                  <strong>{graphRow?.status ?? "created"}</strong>
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
