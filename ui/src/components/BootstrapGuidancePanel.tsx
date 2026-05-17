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

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Setup</p>
          <h3>Bootstrap Guidance</h3>
        </div>
      </div>

      <div className="table-list">
        <div className="table-row">
          <span>Next step</span>
          <strong>{guidanceSummary.nextStep}</strong>
        </div>
        <div className="table-row">
          <span>Required actions</span>
          <strong>{guidanceSummary.requiredActionCount}</strong>
        </div>
        <div className="table-row">
          <span>Optional actions</span>
          <strong>{guidanceSummary.optionalActionCount}</strong>
        </div>
      </div>

      <div className="artifact-stack">
        <article className="artifact-card">
          <div className="artifact-meta">
            <span>run</span>
            <strong>Launch Stack</strong>
          </div>
          <p className="artifact-path">{guidanceSummary.launchCommand}</p>
          <p className="path-label">Backend: {guidanceSummary.backendUrl}</p>
          <p className="path-label">UI: {guidanceSummary.uiUrl}</p>
        </article>
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
                  {item.hint ? <p className="path-label">Do: {item.hint}</p> : null}
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
