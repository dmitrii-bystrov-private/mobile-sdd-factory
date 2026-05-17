import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import type { RuntimeCapabilitiesSummary, RuntimeDefaultsSummary } from "../types";

type RuntimeDefaultsPanelProps = {
  runtimeCapabilities: RuntimeCapabilitiesSummary | null;
  runtimeDefaults: RuntimeDefaultsSummary | null;
  onSaved: (summary: RuntimeDefaultsSummary) => void;
};

type DraftRoleDefault = {
  runner: string;
  model: string;
  effort: string;
};

export function RuntimeDefaultsPanel({
  runtimeCapabilities,
  runtimeDefaults,
  onSaved,
}: RuntimeDefaultsPanelProps): JSX.Element {
  const [defaultRunner, setDefaultRunner] = useState("");
  const [roleDefaults, setRoleDefaults] = useState<Record<string, DraftRoleDefault>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runnerIndex = useMemo(
    () => new Map((runtimeCapabilities?.runners ?? []).map((runner) => [runner.runner, runner])),
    [runtimeCapabilities],
  );

  useEffect(() => {
    if (runtimeCapabilities === null || runtimeDefaults === null) {
      return;
    }
    const resolvedDefaultRunner =
      runtimeDefaults.defaultRunner ??
      runtimeCapabilities.defaultRunner ??
      runtimeCapabilities.availableRunners[0] ??
      "";
    const nextRoleDefaults: Record<string, DraftRoleDefault> = {};
    for (const roleName of runtimeDefaults.knownRoles) {
      const stored = runtimeDefaults.roleDefaults[roleName];
      const runner = stored?.runner ?? resolvedDefaultRunner;
      const runnerCapability = runnerIndex.get(runner);
      const models = runnerCapability?.models ?? [];
      const model = stored?.model ?? models[0]?.id ?? "";
      const modelCapability = models.find((item) => item.id === model);
      const effort =
        stored?.effort ?? modelCapability?.defaultEffort ?? modelCapability?.supportedEfforts[0] ?? "";
      nextRoleDefaults[roleName] = { runner, model, effort };
    }
    setDefaultRunner(resolvedDefaultRunner);
    setRoleDefaults(nextRoleDefaults);
  }, [runnerIndex, runtimeCapabilities, runtimeDefaults]);

  function updateRoleDefault(
    roleName: string,
    patch: Partial<DraftRoleDefault>,
  ): void {
    setRoleDefaults((current) => {
      const next = { ...(current[roleName] ?? { runner: defaultRunner, model: "", effort: "" }), ...patch };
      const runnerCapability = runnerIndex.get(next.runner);
      const models = runnerCapability?.models ?? [];
      if (!models.some((item) => item.id === next.model)) {
        next.model = models[0]?.id ?? "";
      }
      const modelCapability = models.find((item) => item.id === next.model);
      const efforts = modelCapability?.supportedEfforts ?? [];
      if (!efforts.includes(next.effort)) {
        next.effort = modelCapability?.defaultEffort ?? efforts[0] ?? "";
      }
      return {
        ...current,
        [roleName]: next,
      };
    });
  }

  async function handleSave(): Promise<void> {
    if (runtimeDefaults === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await apiClient.updateRuntimeDefaults({
        defaultRunner: defaultRunner || null,
        roleDefaults: Object.fromEntries(
          Object.entries(roleDefaults).map(([roleName, value]) => [
            roleName,
            {
              runner: value.runner || null,
              model: value.model || null,
              effort: value.effort || null,
            },
          ]),
        ),
        knownRoles: runtimeDefaults.knownRoles,
        sourcePath: runtimeDefaults.sourcePath,
      });
      onSaved({
        defaultRunner: saved.default_runner,
        roleDefaults: saved.role_defaults,
        knownRoles: saved.known_roles,
        sourcePath: saved.source_path,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save runtime defaults");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-sidebar">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h2>Runtime Defaults</h2>
        </div>
      </div>

      <p className="path-label">
        Set project-local defaults for new sessions instead of relying only on legacy role metadata.
      </p>

      <label className="form-field">
        <span>Default Runner</span>
        <select
          className="select-input"
          disabled={busy || runtimeCapabilities === null}
          onChange={(event) => setDefaultRunner(event.target.value)}
          value={defaultRunner}
        >
          {(runtimeCapabilities?.availableRunners ?? []).map((runner) => (
            <option key={runner} value={runner}>
              {runner}
            </option>
          ))}
        </select>
      </label>

      <div className="runtime-defaults-list">
        {runtimeDefaults?.knownRoles.map((roleName) => {
          const draft = roleDefaults[roleName];
          const runnerCapability = runnerIndex.get(draft?.runner ?? "");
          const models = runnerCapability?.models ?? [];
          const modelCapability = models.find((item) => item.id === draft?.model);
          const efforts = modelCapability?.supportedEfforts ?? [];
          return (
            <div key={roleName} className="runtime-default-card">
              <strong>{roleName}</strong>
              <div className="followup-form-grid">
                <label className="form-field">
                  <span>Runner</span>
                  <select
                    className="select-input"
                    disabled={busy || runtimeCapabilities === null}
                    onChange={(event) => updateRoleDefault(roleName, { runner: event.target.value })}
                    value={draft?.runner ?? ""}
                  >
                    {(runtimeCapabilities?.availableRunners ?? []).map((runner) => (
                      <option key={runner} value={runner}>
                        {runner}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="form-field">
                  <span>Model</span>
                  <select
                    className="select-input"
                    disabled={busy}
                    onChange={(event) => updateRoleDefault(roleName, { model: event.target.value })}
                    value={draft?.model ?? ""}
                  >
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="form-field">
                <span>Effort</span>
                <select
                  className="select-input"
                  disabled={busy}
                  onChange={(event) => updateRoleDefault(roleName, { effort: event.target.value })}
                  value={draft?.effort ?? ""}
                >
                  {efforts.map((effort) => (
                    <option key={effort} value={effort}>
                      {effort}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          );
        })}
      </div>

      <button className="action-button action-button-strong" disabled={busy || runtimeDefaults === null} onClick={() => void handleSave()} type="button">
        Save Runtime Defaults
      </button>

      {runtimeDefaults ? <p className="path-label">Stored in: {runtimeDefaults.sourcePath}</p> : null}
      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
