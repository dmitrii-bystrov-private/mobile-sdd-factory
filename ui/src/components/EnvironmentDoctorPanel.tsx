import type { EnvironmentDoctorSummary } from "../types";

type EnvironmentDoctorPanelProps = {
  doctorSummary: EnvironmentDoctorSummary | null;
};

export function EnvironmentDoctorPanel({
  doctorSummary,
}: EnvironmentDoctorPanelProps): JSX.Element {
  if (doctorSummary === null) {
    return (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Doctor</p>
            <h3>Environment Health</h3>
          </div>
        </div>
        <p className="path-label">Doctor data has not been loaded yet.</p>
      </section>
    );
  }

  const requiredIssues = doctorSummary.checks.filter(
    (check) => check.required && check.status !== "ok",
  );
  const optionalIssues = doctorSummary.checks.filter(
    (check) => !check.required && check.status !== "ok",
  );
  const nonOkChecks = doctorSummary.checks.filter((check) => check.status !== "ok");
  const overallLabel =
    doctorSummary.overallStatus === "ok"
      ? "Healthy"
      : doctorSummary.overallStatus === "warn"
        ? "Needs attention"
        : "Blocked";

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Doctor</p>
          <h3>Environment Health</h3>
          <p className="path-label">
            Check environment blockers here first.
          </p>
        </div>
      </div>

      <div className="grid-two compact-grid">
        <div className="metric-card">
          <span>Overall</span>
          <strong>{overallLabel}</strong>
        </div>
        <div className="metric-card">
          <span>Required checks</span>
          <strong>
            {doctorSummary.requiredOk}/{doctorSummary.requiredTotal} green
          </strong>
        </div>
        <div className="metric-card">
          <span>Blocking issues</span>
          <strong>{requiredIssues.length}</strong>
        </div>
        <div className="metric-card">
          <span>Optional warnings</span>
          <strong>{optionalIssues.length}</strong>
        </div>
      </div>

      {nonOkChecks.length === 0 ? (
          <div className="inline-summary-card">
            <div className="inline-summary-header">
              <strong>Ready for normal operation</strong>
              <span>all clear</span>
            </div>
          <p className="form-help">
            All required checks are green.
          </p>
        </div>
      ) : (
        <>
          <div className="artifact-stack">
            <p className="eyebrow">Required Attention</p>
            {requiredIssues.length > 0 ? (
              requiredIssues.map((check) => (
                <article className="artifact-card" key={check.id}>
                  <div className="artifact-meta">
                    <span>{check.category}</span>
                    <strong>{check.label}</strong>
                  </div>
                  <p className="artifact-path">{check.details}</p>
                  {check.hint ? <p className="path-label">Do next: {check.hint}</p> : null}
                </article>
              ))
            ) : (
              <p className="path-label">No required issues are currently blocking the environment.</p>
            )}
          </div>

          <div className="artifact-stack">
            <p className="eyebrow">Optional Warnings</p>
            {optionalIssues.length > 0 ? (
              optionalIssues.map((check) => (
                <article className="artifact-card" key={check.id}>
                  <div className="artifact-meta">
                    <span>{check.category}</span>
                    <strong>{check.label}</strong>
                  </div>
                  <p className="artifact-path">{check.details}</p>
                  {check.hint ? <p className="path-label">Suggested fix: {check.hint}</p> : null}
                </article>
              ))
            ) : (
              <p className="path-label">No optional warnings right now.</p>
            )}
          </div>

          <div className="advanced-disclosure">
            <div className="inline-summary-header">
              <strong>Advanced Diagnostics</strong>
              <span>{doctorSummary.repoRoot}</span>
            </div>
            <div className="table-list compact">
              {nonOkChecks.map((check) => (
                <div className="table-row" key={`raw-${check.id}`}>
                  <span>
                    {check.required ? "required" : "optional"} · {check.label}
                  </span>
                  <strong>{check.status}</strong>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
