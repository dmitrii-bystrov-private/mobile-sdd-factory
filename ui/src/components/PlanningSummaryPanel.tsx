import type { PlanningSummary } from "../types";

type PlanningSummaryPanelProps = {
  planningSummary: PlanningSummary | null;
  workflowProfile: string;
};

function summarizeContent(content: string | null | undefined): string {
  if (content === null || content === undefined) {
    return "Artifact captured, detail preview unavailable.";
  }

  const normalized = content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("role=") && !line.startsWith("output_type=") && !line.startsWith("payload="))
    .join(" ");

  if (normalized.length === 0) {
    return "Artifact captured, no compact preview available.";
  }

  return normalized.length > 220 ? `${normalized.slice(0, 217)}...` : normalized;
}

export function PlanningSummaryPanel({
  planningSummary,
  workflowProfile,
}: PlanningSummaryPanelProps): JSX.Element {
  if (workflowProfile !== "story_full") {
    return (
      <section className="subpanel">
        <div className="subpanel-head">
          <strong>Planning Chain</strong>
        </div>
        <p>This workflow profile does not use the extended story-planning chain.</p>
      </section>
    );
  }

  if (planningSummary === null) {
    return (
      <section className="subpanel">
        <div className="subpanel-head">
          <strong>Planning Chain</strong>
        </div>
        <p>No planning chain has been produced for this session yet.</p>
      </section>
    );
  }

  return (
    <section className="subpanel">
      <div className="subpanel-head">
        <strong>Planning Chain</strong>
        <span className="badge badge-muted">
          {planningSummary.completedCount}/{planningSummary.stageCount}
        </span>
      </div>
      <div className="table-list limited-list planning-summary-list">
        {planningSummary.steps.map((step) => (
          <div className="planning-step-card" key={step.stageName}>
            <div className="planning-step-head">
              <div>
                <strong>{step.label}</strong>
                <p>{step.stageName}</p>
              </div>
              <span className={`status-pill status-${step.status}`}>
                {step.status}
              </span>
            </div>
            <p className="planning-step-snippet">
              {summarizeContent(step.artifactDetail?.content)}
            </p>
            <small className="path-label">
              {step.artifactType ?? "artifact pending"}
            </small>
          </div>
        ))}
      </div>
    </section>
  );
}
