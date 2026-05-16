import type { JiraSubtasksSummary } from "../types";

type JiraSubtasksPanelProps = {
  jiraSubtasksSummary: JiraSubtasksSummary | null;
};

function parseLines(content: string | null | undefined): string[] {
  if (content === null || content === undefined) {
    return [];
  }
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "));
}

export function JiraSubtasksPanel({
  jiraSubtasksSummary,
}: JiraSubtasksPanelProps): JSX.Element | null {
  if (jiraSubtasksSummary === null) {
    return null;
  }

  const lines = parseLines(jiraSubtasksSummary.artifactDetail?.content);

  return (
    <section className="subpanel">
      <div className="subpanel-head">
        <strong>Jira Subtasks</strong>
      </div>
      {lines.length > 0 ? (
        <div className="table-list">
          {lines.map((line) => (
            <div className="table-row" key={line}>
              <strong>{line.slice(2)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p>Subtask creation summary is available, but no keys were parsed.</p>
      )}
    </section>
  );
}
