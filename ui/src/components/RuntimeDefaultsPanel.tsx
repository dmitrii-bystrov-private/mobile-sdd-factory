import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import type {
  RequirementsClarificationMode,
  RuntimeCapabilitiesSummary,
  RuntimeDefaultsSummary,
  SessionPolicyValue,
  WorkflowProfile,
} from "../types";

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

type DraftPolicyDefaults = {
  test_policy: SessionPolicyValue;
  self_review_policy: SessionPolicyValue;
  boy_scout_policy: SessionPolicyValue;
  doc_harvest_policy: SessionPolicyValue;
  requirements_clarification_mode: RequirementsClarificationMode;
};

const POLICY_OPTIONS: SessionPolicyValue[] = ["disabled", "enabled", "required"];
const REQUIREMENTS_CLARIFICATION_OPTIONS: RequirementsClarificationMode[] = [
  "ask-a-lot",
  "ask-selectively",
  "autonomous",
];

function defaultPolicyDefaults(): DraftPolicyDefaults {
  return {
    test_policy: "enabled",
    self_review_policy: "enabled",
    boy_scout_policy: "enabled",
    doc_harvest_policy: "enabled",
    requirements_clarification_mode: "ask-selectively",
  };
}

export function RuntimeDefaultsPanel({
  runtimeCapabilities,
  runtimeDefaults,
  onSaved,
}: RuntimeDefaultsPanelProps): JSX.Element {
  const [defaultRunner, setDefaultRunner] = useState("");
  const [roleDefaults, setRoleDefaults] = useState<Record<string, DraftRoleDefault>>({});
  const [policyDefaults, setPolicyDefaults] = useState<Record<WorkflowProfile, DraftPolicyDefaults>>({
    oneshot: defaultPolicyDefaults(),
    bug_full: defaultPolicyDefaults(),
    story_full: defaultPolicyDefaults(),
  });
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
    setPolicyDefaults({
      oneshot: {
        ...defaultPolicyDefaults(),
        ...(runtimeDefaults.policyDefaults.oneshot ?? {}),
      },
      bug_full: {
        ...defaultPolicyDefaults(),
        ...(runtimeDefaults.policyDefaults.bug_full ?? {}),
      },
      story_full: {
        ...defaultPolicyDefaults(),
        ...(runtimeDefaults.policyDefaults.story_full ?? {}),
      },
    });
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

  function updatePolicyDefault<K extends keyof DraftPolicyDefaults>(
    workflowProfile: WorkflowProfile,
    key: K,
    value: DraftPolicyDefaults[K],
  ): void {
    setPolicyDefaults((current) => ({
      ...current,
      [workflowProfile]: {
        ...current[workflowProfile],
        [key]: value,
      },
    }));
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
        policyDefaults: {
          oneshot: {
            self_review_policy: policyDefaults.oneshot.self_review_policy,
            boy_scout_policy: policyDefaults.oneshot.boy_scout_policy,
            doc_harvest_policy: policyDefaults.oneshot.doc_harvest_policy,
          },
          bug_full: {
            test_policy: policyDefaults.bug_full.test_policy,
            self_review_policy: policyDefaults.bug_full.self_review_policy,
            boy_scout_policy: policyDefaults.bug_full.boy_scout_policy,
            doc_harvest_policy: policyDefaults.bug_full.doc_harvest_policy,
          },
          story_full: {
            self_review_policy: policyDefaults.story_full.self_review_policy,
            boy_scout_policy: policyDefaults.story_full.boy_scout_policy,
            doc_harvest_policy: policyDefaults.story_full.doc_harvest_policy,
            requirements_clarification_mode: policyDefaults.story_full.requirements_clarification_mode,
          },
        },
        knownRoles: runtimeDefaults.knownRoles,
        sourcePath: runtimeDefaults.sourcePath,
      });
      onSaved({
        defaultRunner: saved.default_runner,
        roleDefaults: saved.role_defaults,
        policyDefaults: saved.policy_defaults,
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
        <div className="runtime-default-card">
          <strong>oneshot policy defaults</strong>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Self Review</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("oneshot", "self_review_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.oneshot.self_review_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`oneshot-self-review-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Boy Scout</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("oneshot", "boy_scout_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.oneshot.boy_scout_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`oneshot-boy-scout-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="form-field">
            <span>Doc Harvest</span>
            <select
              className="select-input"
              disabled={busy}
              onChange={(event) =>
                updatePolicyDefault("oneshot", "doc_harvest_policy", event.target.value as SessionPolicyValue)
              }
              value={policyDefaults.oneshot.doc_harvest_policy}
            >
              {POLICY_OPTIONS.map((value) => (
                <option key={`oneshot-doc-harvest-${value}`} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="runtime-default-card">
          <strong>bug_full policy defaults</strong>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Test Policy</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("bug_full", "test_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.bug_full.test_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`bug-test-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Self Review</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("bug_full", "self_review_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.bug_full.self_review_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`bug-self-review-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Boy Scout</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("bug_full", "boy_scout_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.bug_full.boy_scout_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`bug-boy-scout-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Doc Harvest</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("bug_full", "doc_harvest_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.bug_full.doc_harvest_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`bug-doc-harvest-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="runtime-default-card">
          <strong>story_full policy defaults</strong>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Self Review</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("story_full", "self_review_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.story_full.self_review_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`story-self-review-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Boy Scout</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("story_full", "boy_scout_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.story_full.boy_scout_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`story-boy-scout-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="followup-form-grid">
            <label className="form-field">
              <span>Doc Harvest</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault("story_full", "doc_harvest_policy", event.target.value as SessionPolicyValue)
                }
                value={policyDefaults.story_full.doc_harvest_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`story-doc-harvest-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Clarification Mode</span>
              <select
                className="select-input"
                disabled={busy}
                onChange={(event) =>
                  updatePolicyDefault(
                    "story_full",
                    "requirements_clarification_mode",
                    event.target.value as RequirementsClarificationMode,
                  )
                }
                value={policyDefaults.story_full.requirements_clarification_mode}
              >
                {REQUIREMENTS_CLARIFICATION_OPTIONS.map((value) => (
                  <option key={`story-clarification-${value}`} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </div>

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
