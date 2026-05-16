import type { InteractiveStateSummary } from "../types";

type InteractiveStatePanelProps = {
  interactiveStateSummary: InteractiveStateSummary | null;
};

export function InteractiveStatePanel({
  interactiveStateSummary,
}: InteractiveStatePanelProps): JSX.Element | null {
  if (interactiveStateSummary === null || !interactiveStateSummary.available) {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Interactive State</p>
          <h3>Live Agent Blocker</h3>
        </div>
      </div>

      <div className="table-list">
        <div className="table-row">
          <span>Role</span>
          <strong>{interactiveStateSummary.roleName ?? "unknown"}</strong>
        </div>
        <div className="table-row">
          <span>Stage</span>
          <strong>{interactiveStateSummary.currentStage ?? "unknown"}</strong>
        </div>
        <div className="table-row">
          <span>Source Event</span>
          <strong>{interactiveStateSummary.sourceEventType ?? "unknown"}</strong>
        </div>
        <div className="table-row">
          <span>Needs Operator Input</span>
          <strong>{interactiveStateSummary.needsOperatorInput ? "yes" : "no"}</strong>
        </div>
      </div>

      {interactiveStateSummary.summary !== null ? (
        <div className="context-card">
          <p className="context-label">Summary</p>
          <p>{interactiveStateSummary.summary}</p>
        </div>
      ) : null}

      {interactiveStateSummary.details !== null ? (
        <div className="context-card">
          <p className="context-label">Details</p>
          <p>{interactiveStateSummary.details}</p>
        </div>
      ) : null}
    </section>
  );
}
