import { useState } from "react";

import { roleDisplayName } from "../roleDisplay";
import type { RuntimeCapabilitiesSummary } from "../types";

type RuntimeCapabilitiesPanelProps = {
  capabilities: RuntimeCapabilitiesSummary | null;
};

export function RuntimeCapabilitiesPanel({
  capabilities,
}: RuntimeCapabilitiesPanelProps): JSX.Element {
  const [showModelCatalog, setShowModelCatalog] = useState(false);
  const [showRoleBaselines, setShowRoleBaselines] = useState(false);

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

  const availableRunners = capabilities.runners.filter((runner) => runner.available);
  const missingRunners = capabilities.runners.filter((runner) => !runner.available);
  const customizedRoles = capabilities.roleDefaults.filter(
    (item) => item.model !== null || item.effort !== null || item.mcpServers.length > 0,
  );

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h3>Capabilities</h3>
          <p className="path-label">
            This surface shows which runners are ready and what defaults new sessions will inherit.
          </p>
        </div>
      </div>

      <div className="grid-two compact-grid">
        <div className="metric-card">
          <span>Default runner</span>
          <strong>{capabilities.defaultRunner ?? "none"}</strong>
        </div>
        <div className="metric-card">
          <span>Ready runners</span>
          <strong>{availableRunners.length}</strong>
        </div>
        <div className="metric-card">
          <span>Missing runners</span>
          <strong>{missingRunners.length}</strong>
        </div>
        <div className="metric-card">
          <span>Roles with custom baselines</span>
          <strong>{customizedRoles.length}</strong>
        </div>
      </div>

      <div className="artifact-stack">
        {capabilities.runners.map((runner) => (
          <article className="artifact-card" key={runner.runner}>
            <div className="artifact-meta">
              <span>{runner.available ? "ready" : "missing"}</span>
              <strong>{runner.runner}</strong>
            </div>
            <p className="artifact-path">
              {runner.available
                ? runner.models.length > 0
                  ? `${runner.models.length} models discovered`
                  : "Runner is ready but no live model catalog was reported"
                : "This runner is not currently available in the local environment."}
            </p>
            <div className="inline-pill-row">
              {capabilities.defaultRunner === runner.runner ? (
                <span className="inline-pill">default for new sessions</span>
              ) : null}
              <span className="inline-pill">
                {runner.supportsCustomModel ? "custom models supported" : "catalog only"}
              </span>
              <span className="inline-pill">
                {runner.available ? "ready for new sessions" : "unavailable"}
              </span>
            </div>
          </article>
        ))}
      </div>

      <div className="advanced-disclosure">
        <button
          className="advanced-disclosure-toggle"
          onClick={() => setShowModelCatalog((value) => !value)}
          aria-expanded={showModelCatalog}
          type="button"
        >
          <div>
            <strong>Advanced Runner Catalog</strong>
            <p>Expand to inspect raw model catalogs and runner discovery sources.</p>
          </div>
          <span className={`chevron${showModelCatalog ? " expanded" : ""}`} aria-hidden="true" />
        </button>
        {showModelCatalog ? (
          <div className="advanced-disclosure-body">
            {capabilities.runners.map((runner) => (
              <article className="artifact-card" key={`catalog-${runner.runner}`}>
                <div className="artifact-meta">
                  <span>{runner.available ? "ready" : "missing"}</span>
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
        ) : null}
      </div>

      <div className="advanced-disclosure">
        <button
          className="advanced-disclosure-toggle"
          onClick={() => setShowRoleBaselines((value) => !value)}
          aria-expanded={showRoleBaselines}
          type="button"
        >
          <div>
            <strong>Advanced Role Baselines</strong>
            <p>Expand to inspect per-role model, effort, and MCP baseline settings.</p>
          </div>
          <span className={`chevron${showRoleBaselines ? " expanded" : ""}`} aria-hidden="true" />
        </button>
        {showRoleBaselines ? (
          <div className="advanced-disclosure-body">
            {capabilities.roleDefaults.map((item) => (
              <article className="artifact-card" key={item.roleName}>
                <div className="artifact-meta">
                  <span>{item.effort ?? "no effort"}</span>
                  <strong>{roleDisplayName(item.roleName)}</strong>
                </div>
                <p className="artifact-path">
                  id: {item.roleName} · model: {item.model ?? "none"} · mcp:{" "}
                  {item.mcpServers.join(", ") || "none"}
                </p>
              </article>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
