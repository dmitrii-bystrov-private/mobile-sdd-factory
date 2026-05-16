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

  const nonOkChecks = doctorSummary.checks.filter((check) => check.status !== "ok");

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Doctor</p>
          <h3>Environment Health</h3>
        </div>
      </div>

      <div className="table-list">
        <div className="table-row">
          <span>Overall</span>
          <strong>{doctorSummary.overallStatus}</strong>
        </div>
        <div className="table-row">
          <span>Required</span>
          <strong>
            {doctorSummary.requiredOk}/{doctorSummary.requiredTotal}
          </strong>
        </div>
        <div className="table-row">
          <span>Optional warnings</span>
          <strong>{doctorSummary.optionalWarnings}</strong>
        </div>
      </div>

      {nonOkChecks.length === 0 ? (
        <p className="path-label">All required checks are green.</p>
      ) : (
        <div className="artifact-stack">
          {nonOkChecks.map((check) => (
            <article className="artifact-card" key={check.id}>
              <div className="artifact-meta">
                <span>{check.category}</span>
                <strong>{check.label}</strong>
              </div>
              <p className="artifact-path">
                {check.required ? "required" : "optional"} · {check.status}
              </p>
              <p className="artifact-path">{check.details}</p>
              {check.hint ? <p className="path-label">Hint: {check.hint}</p> : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
