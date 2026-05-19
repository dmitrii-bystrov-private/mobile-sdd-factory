import type { BootstrapGuidanceSummary } from "../types";

type BootstrapGuidancePanelProps = {
  guidanceSummary: BootstrapGuidanceSummary | null;
};

export function BootstrapGuidancePanel({
  guidanceSummary,
}: BootstrapGuidancePanelProps): JSX.Element {
  if (guidanceSummary === null) {
    return (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Setup</p>
            <h3>Bootstrap Guidance</h3>
          </div>
        </div>
        <p className="path-label">Bootstrap guidance has not been loaded yet.</p>
      </section>
    );
  }

  const overallLabel =
    guidanceSummary.requiredActionCount === 0 ? "Ready to launch" : "Setup work required";

  return (
    <section className="panel">
        <div className="panel-header">
        <div>
          <p className="eyebrow">Setup</p>
          <h3>Bootstrap Guidance</h3>
          <p className="path-label">
            Use this when the local stack is not ready yet.
          </p>
        </div>
      </div>

      <div className="grid-two compact-grid">
        <div className="metric-card">
          <span>Overall</span>
          <strong>{overallLabel}</strong>
        </div>
        <div className="metric-card">
          <span>Next step</span>
          <strong>{guidanceSummary.nextStep}</strong>
        </div>
        <div className="metric-card">
          <span>Required actions</span>
          <strong>{guidanceSummary.requiredActionCount}</strong>
        </div>
        <div className="metric-card">
          <span>Optional improvements</span>
          <strong>{guidanceSummary.optionalActionCount}</strong>
        </div>
      </div>

      <div className="inline-summary-card">
        <div className="inline-summary-header">
          <strong>Launch the local stack</strong>
        </div>
        <p className="form-help bootstrap-command">{guidanceSummary.launchCommand}</p>
        <div className="inline-pill-row">
          <span className="inline-pill">Backend: {guidanceSummary.backendUrl}</span>
          <span className="inline-pill">UI: {guidanceSummary.uiUrl}</span>
        </div>
      </div>

      {[
        { title: "Required actions", items: guidanceSummary.requiredActions },
        { title: "Optional improvements", items: guidanceSummary.optionalActions },
      ].map(({ title, items }) => (
          <div className="artifact-stack" key={title}>
            <p className="eyebrow">{title}</p>
            {items.length > 0 ? (
              items.map((item) => (
                <article className="artifact-card" key={item.id}>
                  <div className="artifact-meta">
                    <span>{item.status}</span>
                    <strong>{item.label}</strong>
                  </div>
                  <p className="artifact-path">{item.details}</p>
                  {item.hint ? <p className="path-label">Do next: {item.hint}</p> : null}
                </article>
              ))
            ) : (
              <p className="path-label">None.</p>
            )}
          </div>
        ))}
    </section>
  );
}
