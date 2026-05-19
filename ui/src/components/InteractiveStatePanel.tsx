import { roleDisplayName } from "../roleDisplay";
import { stageDisplayName } from "../stageDisplay";
import type { InteractiveStateSummary } from "../types";

type InteractiveStatePanelProps = {
  interactiveStateSummary: InteractiveStateSummary | null;
};

function formatReason(reason: string | null): string {
  if (!reason) {
    return "unknown";
  }
  return reason
    .split("_")
    .filter((part) => part.length > 0)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

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
          <p className="path-label">
            This run needs operator attention before the active workflow can continue.
          </p>
        </div>
      </div>

      <div className="table-list">
        <div className="table-row">
          <span>Role</span>
          <strong>{roleDisplayName(interactiveStateSummary.roleName)}</strong>
        </div>
        <div className="table-row">
          <span>Stage</span>
          <strong>{stageDisplayName(interactiveStateSummary.currentStage)}</strong>
        </div>
        <div className="table-row">
          <span>Reason</span>
          <strong>{formatReason(interactiveStateSummary.sourceReason)}</strong>
        </div>
        <div className="table-row">
          <span>Operator Action</span>
          <strong>
            {interactiveStateSummary.needsOperatorInput ? "Reply in runtime" : "Use recovery controls"}
          </strong>
        </div>
        {interactiveStateSummary.resumeStrategy === "reactivate_only" ? (
          <div className="table-row">
            <span>Recovery Mode</span>
            <strong>Runtime reactivation needed</strong>
          </div>
        ) : null}
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

      {(interactiveStateSummary.sourceEventType !== null ||
        interactiveStateSummary.resumeStrategy !== null) ? (
        <details className="advanced-disclosure">
          <summary className="advanced-inline-summary">
            <strong>Debug Details</strong>
            <span className="chevron" aria-hidden="true" />
          </summary>
          <div className="advanced-disclosure-body">
            {interactiveStateSummary.sourceEventType !== null ? (
              <div className="table-row">
                <span>Source Event</span>
                <strong>{interactiveStateSummary.sourceEventType}</strong>
              </div>
            ) : null}
            {interactiveStateSummary.resumeStrategy !== null ? (
              <div className="table-row">
                <span>Resume Strategy</span>
                <strong>{interactiveStateSummary.resumeStrategy}</strong>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </section>
  );
}
