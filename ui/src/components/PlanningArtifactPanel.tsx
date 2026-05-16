import type { PlanningSummary } from "../types";

type PlanningArtifactPanelProps = {
  planningSummary: PlanningSummary | null;
  workflowProfile: string;
};

function normalizeContent(content: string | null | undefined): string {
  if (content === null || content === undefined) {
    return "Artifact detail is unavailable.";
  }

  const normalized = content.trim();
  return normalized.length === 0 ? "Artifact detail is empty." : normalized;
}

export function PlanningArtifactPanel({
  planningSummary,
  workflowProfile,
}: PlanningArtifactPanelProps): JSX.Element | null {
  if (workflowProfile !== "story_full" || planningSummary === null) {
    return null;
  }

  const stepsWithArtifacts = planningSummary.steps.filter(
    (step) => step.artifactDetail !== null,
  );

  if (stepsWithArtifacts.length === 0) {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Planning Package</p>
          <h3>Planning Artifacts</h3>
        </div>
        <span className="badge badge-muted">{stepsWithArtifacts.length}</span>
      </div>

      <div className="table-list">
        {stepsWithArtifacts.map((step) => (
          <div className="planning-artifact-card" key={step.stageName}>
            <div className="planning-step-head">
              <div>
                <strong>{step.label}</strong>
                <p>{step.artifactDetail?.artifact_type ?? step.artifactType}</p>
              </div>
              <span className={`status-pill status-${step.status}`}>
                {step.status}
              </span>
            </div>
            <small className="path-label">{step.artifactDetail?.path}</small>
            <pre className="planning-artifact-content">
              {normalizeContent(step.artifactDetail?.content)}
            </pre>
          </div>
        ))}
      </div>
    </section>
  );
}
