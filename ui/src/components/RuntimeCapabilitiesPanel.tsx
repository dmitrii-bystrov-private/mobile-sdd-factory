import { roleDisplayName } from "../roleDisplay";
import type { RuntimeCapabilitiesSummary } from "../types";

type RuntimeCapabilitiesPanelProps = {
  capabilities: RuntimeCapabilitiesSummary | null;
};

export function RuntimeCapabilitiesPanel({
  capabilities,
}: RuntimeCapabilitiesPanelProps): JSX.Element {
  if (capabilities === null) {
    return (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Runtime</p>
            <h3>Capabilities</h3>
          </div>
        </div>
        <p className="path-label">Runtime capability data has not been loaded yet.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h3>Capabilities</h3>
        </div>
      </div>

      <div className="table-list">
        <div className="table-row">
          <span>Available runners</span>
          <strong>{capabilities.availableRunners.join(", ") || "none"}</strong>
        </div>
        <div className="table-row">
          <span>Default runner</span>
          <strong>{capabilities.defaultRunner ?? "none"}</strong>
        </div>
      </div>

      <div className="artifact-stack">
        {capabilities.runners.map((runner) => (
          <article className="artifact-card" key={runner.runner}>
            <div className="artifact-meta">
              <span>{runner.available ? "available" : "missing"}</span>
              <strong>{runner.runner}</strong>
            </div>
            <p className="artifact-path">{runner.source}</p>
            {runner.models.length > 0 ? (
              <div className="table-list compact">
                {runner.models.map((model) => (
                  <div className="table-row" key={`${runner.runner}-${model.id}`}>
                    <span>{model.label}</span>
                    <strong>
                      {model.id} · {model.supportedEfforts.join(", ")}
                    </strong>
                  </div>
                ))}
              </div>
            ) : (
              <p className="path-label">No live model catalog discovered.</p>
            )}
          </article>
        ))}
      </div>

      <div className="artifact-stack">
        <p className="eyebrow">Role Baselines</p>
        {capabilities.roleDefaults.map((item) => (
          <article className="artifact-card" key={item.roleName}>
            <div className="artifact-meta">
              <span>{item.effort ?? "no effort"}</span>
              <strong>{roleDisplayName(item.roleName)}</strong>
            </div>
            <p className="artifact-path">
              id: {item.roleName} · model: {item.model ?? "none"} · mcp: {item.mcpServers.join(", ") || "none"}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
