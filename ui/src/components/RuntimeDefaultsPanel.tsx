import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import { roleDisplayName } from "../roleDisplay";
import { workflowProfileDisplayName } from "../sessionDisplay";
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
const POLICY_OPTION_LABELS: Record<SessionPolicyValue, string> = {
  disabled: "Disabled",
  enabled: "Agent decides",
  required: "Required",
};
const REQUIREMENTS_CLARIFICATION_LABELS: Record<RequirementsClarificationMode, string> = {
  "ask-a-lot": "Ask often",
  "ask-selectively": "Ask selectively",
  autonomous: "Stay autonomous",
};

const POLICY_DEFAULT_DESCRIPTIONS: Record<
  "test_policy" | "self_review_policy" | "boy_scout_policy" | "doc_harvest_policy",
  string
> = {
  test_policy: "Choose whether the bug flow treats testing as disabled, auto-started with agent skip semantics, or required.",
  self_review_policy:
    "Choose whether the self-review lane is disabled, auto-started with agent skip semantics, or required.",
  boy_scout_policy:
    "Choose whether the Boy Scout lane is disabled, auto-started with agent skip semantics, or required.",
  doc_harvest_policy:
    "Choose whether doc harvest is disabled, auto-started with agent skip semantics, or required.",
};

const CLARIFICATION_MODE_DESCRIPTIONS: Record<RequirementsClarificationMode, string> = {
  "ask-a-lot": "Bias toward interactive clarification whenever story requirements are incomplete or ambiguous.",
  "ask-selectively": "Ask only when ambiguity is likely to change implementation or planning decisions.",
  autonomous: "Carry the story forward without clarification unless the flow hard-blocks.",
};

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
  const [policyProfileView, setPolicyProfileView] = useState<WorkflowProfile>("oneshot");
  const [showRoleDefaults, setShowRoleDefaults] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runnerIndex = useMemo(
    () => new Map((runtimeCapabilities?.runners ?? []).map((runner) => [runner.runner, runner])),
    [runtimeCapabilities],
  );
  const roleDefaultsIndex = useMemo(
    () => new Map((runtimeCapabilities?.roleDefaults ?? []).map((role) => [role.roleName, role])),
    [runtimeCapabilities],
  );

  function inheritedRoleDefault(
    roleName: string,
    resolvedDefaultRunner: string,
  ): DraftRoleDefault {
    const runnerCapability = runnerIndex.get(resolvedDefaultRunner);
    const roleDefault = roleDefaultsIndex.get(roleName);
    const models = runnerCapability?.models ?? [];
    const modelIds = models.map((item) => item.id);
    const compatibleRoleModel =
      roleDefault?.model && modelIds.includes(roleDefault.model) ? roleDefault.model : undefined;
    const model = compatibleRoleModel ?? models[0]?.id ?? "";
    const modelCapability = models.find((item) => item.id === model);
    const supportedEfforts = modelCapability?.supportedEfforts ?? [];
    const compatibleRoleEffort =
      compatibleRoleModel === model &&
      roleDefault?.effort &&
      (supportedEfforts.length === 0 || supportedEfforts.includes(roleDefault.effort))
        ? roleDefault.effort
        : undefined;
    const effort =
      compatibleRoleEffort ??
      modelCapability?.defaultEffort ??
      supportedEfforts[0] ??
      "";
    return {
      runner: resolvedDefaultRunner,
      model,
      effort,
    };
  }

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
      if (stored) {
        const inherited = inheritedRoleDefault(roleName, stored.runner ?? resolvedDefaultRunner);
        nextRoleDefaults[roleName] = {
          runner: stored.runner ?? resolvedDefaultRunner,
          model: stored.model ?? inherited.model,
          effort: stored.effort ?? inherited.effort,
        };
        continue;
      }
      nextRoleDefaults[roleName] = inheritedRoleDefault(roleName, resolvedDefaultRunner);
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
  }, [roleDefaultsIndex, runnerIndex, runtimeCapabilities, runtimeDefaults]);

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

  function handleDefaultRunnerChange(nextRunner: string): void {
    setRoleDefaults((current) => {
      const nextRoleDefaults: Record<string, DraftRoleDefault> = {};
      for (const roleName of runtimeDefaults?.knownRoles ?? []) {
        const currentValue = current[roleName] ?? inheritedRoleDefault(roleName, defaultRunner);
        const currentInherited = inheritedRoleDefault(roleName, defaultRunner);
        if (
          currentValue.runner === currentInherited.runner &&
          currentValue.model === currentInherited.model &&
          currentValue.effort === currentInherited.effort
        ) {
          nextRoleDefaults[roleName] = inheritedRoleDefault(roleName, nextRunner);
          continue;
        }
        nextRoleDefaults[roleName] = currentValue;
      }
      return nextRoleDefaults;
    });
    setDefaultRunner(nextRunner);
  }

  async function handleSave(): Promise<void> {
    if (runtimeDefaults === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const normalizedDefaultRunner = defaultRunner || null;
      const explicitRoleDefaults = Object.fromEntries(
        Object.entries(roleDefaults).flatMap(([roleName, value]) => {
          const inherited = inheritedRoleDefault(roleName, defaultRunner);
          if (
            value.runner === inherited.runner &&
            value.model === inherited.model &&
            value.effort === inherited.effort
          ) {
            return [];
          }
          return [[
            roleName,
            {
              runner: value.runner || null,
              model: value.model || null,
              effort: value.effort || null,
            },
          ]];
        }),
      );
      const saved = await apiClient.updateRuntimeDefaults({
        defaultRunner: normalizedDefaultRunner,
        roleDefaults: explicitRoleDefaults,
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
        Set project defaults for new sessions. Lane-specific runtime overrides stay in advanced settings.
      </p>

      <div className="runtime-default-card">
        <div className="inline-summary-header">
          <strong>Project Baseline</strong>
          <span>{runtimeDefaults?.knownRoles.length ?? 0} known roles</span>
        </div>
        <label className="form-field">
          <span>Default Runner</span>
          <select
            className="select-input"
            disabled={busy || runtimeCapabilities === null}
            onChange={(event) => handleDefaultRunnerChange(event.target.value)}
            value={defaultRunner}
          >
            {(runtimeCapabilities?.availableRunners ?? []).map((runner) => (
              <option key={runner} value={runner}>
                {runner}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="runtime-defaults-list">
        <div className="inline-pill-row">
          {(["oneshot", "bug_full", "story_full"] as const).map((profile) => (
            <button
              key={profile}
              className={`inline-pill inline-pill-button ${policyProfileView === profile ? "selected" : ""}`}
              onClick={() => setPolicyProfileView(profile)}
              type="button"
            >
              {workflowProfileDisplayName(profile)}
            </button>
          ))}
        </div>

        {policyProfileView === "oneshot" ? (
            <div className="runtime-default-card">
              <div className="inline-summary-header">
                <strong>{workflowProfileDisplayName("oneshot")}</strong>
              </div>
            <div className="followup-form-grid">
              <label className="form-field">
                <span>Self Review</span>
                <select
                  className="select-input"
                  disabled={busy}
                  onChange={(event) =>
                    updatePolicyDefault("oneshot", "self_review_policy", event.target.value as SessionPolicyValue)
                  }
                  title={POLICY_DEFAULT_DESCRIPTIONS.self_review_policy}
                  value={policyDefaults.oneshot.self_review_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`oneshot-self-review-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={POLICY_DEFAULT_DESCRIPTIONS.boy_scout_policy}
                  value={policyDefaults.oneshot.boy_scout_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`oneshot-boy-scout-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                title={POLICY_DEFAULT_DESCRIPTIONS.doc_harvest_policy}
                value={policyDefaults.oneshot.doc_harvest_policy}
              >
                {POLICY_OPTIONS.map((value) => (
                  <option key={`oneshot-doc-harvest-${value}`} value={value}>
                    {POLICY_OPTION_LABELS[value]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        {policyProfileView === "bug_full" ? (
            <div className="runtime-default-card">
              <div className="inline-summary-header">
                <strong>{workflowProfileDisplayName("bug_full")}</strong>
              </div>
            <div className="followup-form-grid">
              <label className="form-field">
                <span>Test Policy</span>
                <select
                  className="select-input"
                  disabled={busy}
                  onChange={(event) =>
                    updatePolicyDefault("bug_full", "test_policy", event.target.value as SessionPolicyValue)
                  }
                  title={POLICY_DEFAULT_DESCRIPTIONS.test_policy}
                  value={policyDefaults.bug_full.test_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`bug-test-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={POLICY_DEFAULT_DESCRIPTIONS.self_review_policy}
                  value={policyDefaults.bug_full.self_review_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`bug-self-review-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={POLICY_DEFAULT_DESCRIPTIONS.boy_scout_policy}
                  value={policyDefaults.bug_full.boy_scout_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`bug-boy-scout-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={POLICY_DEFAULT_DESCRIPTIONS.doc_harvest_policy}
                  value={policyDefaults.bug_full.doc_harvest_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`bug-doc-harvest-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        ) : null}

        {policyProfileView === "story_full" ? (
            <div className="runtime-default-card">
              <div className="inline-summary-header">
                <strong>{workflowProfileDisplayName("story_full")}</strong>
              </div>
            <div className="followup-form-grid">
              <label className="form-field">
                <span>Self Review</span>
                <select
                  className="select-input"
                  disabled={busy}
                  onChange={(event) =>
                    updatePolicyDefault("story_full", "self_review_policy", event.target.value as SessionPolicyValue)
                  }
                  title={POLICY_DEFAULT_DESCRIPTIONS.self_review_policy}
                  value={policyDefaults.story_full.self_review_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`story-self-review-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={POLICY_DEFAULT_DESCRIPTIONS.boy_scout_policy}
                  value={policyDefaults.story_full.boy_scout_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`story-boy-scout-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={POLICY_DEFAULT_DESCRIPTIONS.doc_harvest_policy}
                  value={policyDefaults.story_full.doc_harvest_policy}
                >
                  {POLICY_OPTIONS.map((value) => (
                    <option key={`story-doc-harvest-${value}`} value={value}>
                      {POLICY_OPTION_LABELS[value]}
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
                  title={CLARIFICATION_MODE_DESCRIPTIONS[policyDefaults.story_full.requirements_clarification_mode]}
                  value={policyDefaults.story_full.requirements_clarification_mode}
                >
                  {REQUIREMENTS_CLARIFICATION_OPTIONS.map((value) => (
                    <option key={`story-clarification-${value}`} value={value}>
                      {REQUIREMENTS_CLARIFICATION_LABELS[value]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        ) : null}
      </div>

      <div className="advanced-disclosure">
        <button
          className="advanced-disclosure-toggle"
          onClick={() => setShowRoleDefaults((current) => !current)}
          aria-expanded={showRoleDefaults}
          type="button"
        >
          <div>
            <strong>Advanced Role Overrides</strong>
            <p>
              Change runner/model/effort for specific lanes when the project-wide baseline is not enough.
            </p>
          </div>
          <div className="advanced-disclosure-meta">
            <small>{runtimeDefaults?.knownRoles.length ?? 0} roles</small>
            <span className={`chevron${showRoleDefaults ? " expanded" : ""}`} aria-hidden="true" />
          </div>
        </button>
        {showRoleDefaults ? (
          <div className="advanced-disclosure-body runtime-defaults-list">
            {runtimeDefaults?.knownRoles.map((roleName) => {
              const draft = roleDefaults[roleName];
              const runnerCapability = runnerIndex.get(draft?.runner ?? "");
              const models = runnerCapability?.models ?? [];
              const modelCapability = models.find((item) => item.id === draft?.model);
              const efforts = modelCapability?.supportedEfforts ?? [];
              return (
                <div key={roleName} className="runtime-default-card">
                  <div className="inline-summary-header">
                    <strong>{roleDisplayName(roleName)}</strong>
                    <span>{draft?.runner ?? "runner?"}</span>
                  </div>
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
        ) : null}
      </div>

      <button
        className="action-button action-button-strong"
        disabled={busy || runtimeDefaults === null}
        onClick={() => void handleSave()}
        title="Save these runtime and policy defaults for future sessions in this project."
        type="button"
      >
        Save Runtime Defaults
      </button>

      {error ? <p className="error-banner">{error}</p> : null}
    </section>
  );
}
