import { useEffect, useMemo, useRef, useState } from "react";

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

type SessionStartFormProps = {
  onCreated: (sessionId: number) => Promise<void>;
  runtimeCapabilities: RuntimeCapabilitiesSummary | null;
  runtimeDefaults: RuntimeDefaultsSummary | null;
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

const WORKFLOW_PROFILE_DESCRIPTIONS: Record<WorkflowProfile, string> = {
  oneshot: "Single-task flow without story decomposition or bug-only recovery lanes.",
  bug_full: "Bug-oriented flow with dedicated bug-fix and test policy handling.",
  story_full: "Full story planning and execution flow with clarification, spec, and subtask stages.",
};

const POLICY_DESCRIPTIONS: Record<
  "test_policy" | "self_review_policy" | "boy_scout_policy" | "doc_harvest_policy",
  string
> = {
  test_policy: "Controls whether the bug flow treats testing as optional, agent-decided, or mandatory.",
  self_review_policy:
    "Controls whether the self-review lane is disabled, auto-started with agent skip semantics, or required.",
  boy_scout_policy:
    "Controls whether the code-scout lane is disabled, auto-started with agent skip semantics, or required.",
  doc_harvest_policy:
    "Controls whether documentation follow-up is disabled, auto-started with agent skip semantics, or required.",
};

const CLARIFICATION_MODE_DESCRIPTIONS: Record<RequirementsClarificationMode, string> = {
  "ask-a-lot": "Bias toward interactive clarification whenever the spec is incomplete or ambiguous.",
  "ask-selectively": "Ask only when ambiguity is likely to change implementation or planning decisions.",
  autonomous: "Prefer carrying the task forward without operator clarification unless the flow hard-blocks.",
};

type DraftPolicy = {
  test_policy: SessionPolicyValue;
  self_review_policy: SessionPolicyValue;
  boy_scout_policy: SessionPolicyValue;
  doc_harvest_policy: SessionPolicyValue;
  requirements_clarification_mode: RequirementsClarificationMode;
};

function defaultDraftPolicy(): DraftPolicy {
  return {
    test_policy: "enabled",
    self_review_policy: "enabled",
    boy_scout_policy: "enabled",
    doc_harvest_policy: "enabled",
    requirements_clarification_mode: "ask-selectively",
  };
}

function mergePolicyDefaults(
  base: DraftPolicy,
  overrides: Record<string, string> | undefined,
): DraftPolicy {
  return {
    test_policy: (overrides?.test_policy as SessionPolicyValue | undefined) ?? base.test_policy,
    self_review_policy:
      (overrides?.self_review_policy as SessionPolicyValue | undefined) ?? base.self_review_policy,
    boy_scout_policy:
      (overrides?.boy_scout_policy as SessionPolicyValue | undefined) ?? base.boy_scout_policy,
    doc_harvest_policy:
      (overrides?.doc_harvest_policy as SessionPolicyValue | undefined) ?? base.doc_harvest_policy,
    requirements_clarification_mode:
      (overrides?.requirements_clarification_mode as RequirementsClarificationMode | undefined) ??
      base.requirements_clarification_mode,
  };
}

export function SessionStartForm({
  onCreated,
  runtimeCapabilities,
  runtimeDefaults,
}: SessionStartFormProps): JSX.Element {
  const [taskKey, setTaskKey] = useState("");
  const [workflowProfile, setWorkflowProfile] = useState<WorkflowProfile>("oneshot");
  const [policy, setPolicy] = useState<DraftPolicy>(defaultDraftPolicy());
  const [roleConfig, setRoleConfig] = useState<Record<string, { runner: string; model: string; effort: string }>>({});
  const [showPolicyTuning, setShowPolicyTuning] = useState(false);
  const [showAdvancedRoleConfig, setShowAdvancedRoleConfig] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previousPrefillRef = useRef<Record<string, { runner: string; model: string; effort: string }>>({});

  const showTestPolicy = workflowProfile === "bug_full";
  const showRequirementsClarificationMode = workflowProfile === "story_full";
  const normalizedTaskKey = taskKey.trim().toUpperCase();
  const enabledOptionalLaneCount = [
    policy.self_review_policy,
    policy.boy_scout_policy,
    policy.doc_harvest_policy,
  ].filter((value) => value !== "disabled").length;

  const payload = useMemo(() => {
    const basePolicy = {
      self_review_policy: policy.self_review_policy,
      boy_scout_policy: policy.boy_scout_policy,
      doc_harvest_policy: policy.doc_harvest_policy,
    };
    if (workflowProfile === "bug_full") {
      return {
        workflow_profile: workflowProfile,
        policy: {
          ...basePolicy,
          test_policy: policy.test_policy,
        },
      };
    }
    if (workflowProfile === "story_full") {
      return {
        workflow_profile: workflowProfile,
        policy: {
          ...basePolicy,
          requirements_clarification_mode: policy.requirements_clarification_mode,
        },
      };
    }
    return {
      workflow_profile: workflowProfile,
      policy: basePolicy,
    };
  }, [policy, workflowProfile]);

  const effectiveRoleNames = useMemo(() => {
    const roleNames = [
      "implementer",
      "verification-coordinator",
      "mr-comments-analyst-worker",
    ];
    if (workflowProfile === "bug_full") {
      roleNames.push("bug-fixer");
    }
    if (policy.self_review_policy !== "disabled") {
      roleNames.push("code-reviewer");
    }
    if (policy.boy_scout_policy !== "disabled") {
      roleNames.push("code-scout");
    }
    if (policy.doc_harvest_policy !== "disabled") {
      roleNames.push("doc-harvest-worker");
    }
    if (workflowProfile === "story_full") {
      roleNames.push(
        "proposal-context-worker",
        "requirements-clarifier-worker",
        "acceptance-criteria-worker",
        "constraints-worker",
        "spec-verifier-worker",
        "story-spec-worker",
        "task-decomposer-worker",
      );
    }
    return roleNames;
  }, [
    policy.boy_scout_policy,
    policy.doc_harvest_policy,
    policy.self_review_policy,
    workflowProfile,
  ]);

  useEffect(() => {
    setPolicy(
      mergePolicyDefaults(defaultDraftPolicy(), runtimeDefaults?.policyDefaults[workflowProfile]),
    );
  }, [runtimeDefaults, workflowProfile]);

  useEffect(() => {
    if (runtimeCapabilities === null) {
      return;
    }

    const runnerIndex = new Map(runtimeCapabilities.runners.map((runner) => [runner.runner, runner]));
    const roleDefaultsIndex = new Map(runtimeCapabilities.roleDefaults.map((item) => [item.roleName, item]));
    const defaultRunner =
      runtimeDefaults?.defaultRunner ??
      runtimeCapabilities.defaultRunner ??
      runtimeCapabilities.availableRunners[0] ??
      "claude";

    function defaultConfigForRole(roleName: string): { runner: string; model: string; effort: string } {
      const storedRoleDefault = runtimeDefaults?.roleDefaults[roleName];
      const runner = storedRoleDefault?.runner ?? defaultRunner;
      const runnerCapability = runnerIndex.get(runner);
      const roleDefault = roleDefaultsIndex.get(roleName);
      const models = runnerCapability?.models ?? [];
      const modelIds = models.map((item) => item.id);
      const compatibleRoleModel =
        roleDefault?.model && modelIds.includes(roleDefault.model) ? roleDefault.model : undefined;
      const model =
        (storedRoleDefault?.runner === null || storedRoleDefault?.runner === runner ? storedRoleDefault?.model : null) ??
        compatibleRoleModel ??
        (runner === "claude" ? models.find((item) => item.id === "sonnet")?.id : undefined) ??
        models[0]?.id ??
        "";
      const modelCapability = models.find((item) => item.id === model);
      const supportedEfforts = modelCapability?.supportedEfforts ?? [];
      const compatibleRoleEffort =
        compatibleRoleModel === model &&
        roleDefault?.effort &&
        (supportedEfforts.length === 0 || supportedEfforts.includes(roleDefault.effort))
          ? roleDefault.effort
          : undefined;
      const effort =
        (
          (storedRoleDefault?.runner === null || storedRoleDefault?.runner === runner) &&
          (storedRoleDefault?.model === null || storedRoleDefault?.model === model)
            ? storedRoleDefault?.effort
            : null
        ) ??
        compatibleRoleEffort ??
        modelCapability?.defaultEffort ??
        supportedEfforts[0] ??
        "medium";
      return { runner, model, effort };
    }

    const nextPrefill: Record<string, { runner: string; model: string; effort: string }> = {};
    for (const roleName of effectiveRoleNames) {
      nextPrefill[roleName] = defaultConfigForRole(roleName);
    }
    const previousPrefill = previousPrefillRef.current;
    setRoleConfig((current) => {
      const next: Record<string, { runner: string; model: string; effort: string }> = {};
      for (const roleName of effectiveRoleNames) {
        const currentValue = current[roleName];
        const previousValue = previousPrefill[roleName];
        const hasManualOverride =
          currentValue !== undefined &&
          previousValue !== undefined &&
          (currentValue.runner !== previousValue.runner ||
            currentValue.model !== previousValue.model ||
            currentValue.effort !== previousValue.effort);
        next[roleName] = hasManualOverride
          ? currentValue
          : nextPrefill[roleName];
      }
      return next;
    });
    previousPrefillRef.current = nextPrefill;
  }, [effectiveRoleNames, runtimeCapabilities, runtimeDefaults]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (normalizedTaskKey.length === 0) {
      setError("Task key is required");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const created = await apiClient.createSession({
        task_key: normalizedTaskKey,
        workflow_profile: payload.workflow_profile,
        prepare: true,
        policy: payload.policy,
        role_config: roleConfig,
      });
      await onCreated(created.session.id);
      setTaskKey("");
      setWorkflowProfile("oneshot");
      setPolicy(defaultDraftPolicy());
      setRoleConfig({});
      previousPrefillRef.current = {};
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start session");
    } finally {
      setBusy(false);
    }
  }

  function updatePolicy<K extends keyof DraftPolicy>(key: K, value: DraftPolicy[K]): void {
    setPolicy((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function updateRoleConfig(
    roleName: string,
    patch: Partial<{ runner: string; model: string; effort: string }>,
  ): void {
    if (runtimeCapabilities === null) {
      return;
    }
    const runnerIndex = new Map(runtimeCapabilities.runners.map((runner) => [runner.runner, runner]));
    setRoleConfig((current) => {
      const existing = current[roleName] ?? { runner: "", model: "", effort: "" };
      const next = { ...existing, ...patch };
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

  return (
    <section className="panel panel-sidebar">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Start Session</p>
          <h2>New Workflow Run</h2>
        </div>
      </div>

      <p className="path-label">
        Start a task run here. Change policies or lane overrides only when this run should differ from the defaults.
      </p>

      <form className="session-start-form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="form-field">
          <span>Task Key</span>
          <input
            className="text-input"
            onChange={(event) => setTaskKey(event.target.value)}
            placeholder="IOS-1234"
            value={taskKey}
          />
        </label>

        <label className="form-field">
          <span>Workflow Profile</span>
          <select
            className="select-input"
            onChange={(event) => setWorkflowProfile(event.target.value as WorkflowProfile)}
            value={workflowProfile}
          >
            <option value="oneshot">{workflowProfileDisplayName("oneshot")}</option>
            <option value="bug_full">{workflowProfileDisplayName("bug_full")}</option>
            <option value="story_full">{workflowProfileDisplayName("story_full")}</option>
          </select>
        </label>

        <div className="inline-summary-card">
          <div className="inline-summary-header">
            <strong>{workflowProfileDisplayName(workflowProfile)}</strong>
            <span>{effectiveRoleNames.length} workers</span>
          </div>
          <p className="form-help">
            {WORKFLOW_PROFILE_DESCRIPTIONS[workflowProfile]}
          </p>
          <div className="inline-pill-row">
            <span className="inline-pill">Self-review {policy.self_review_policy}</span>
            <span className="inline-pill">Boy Scout {policy.boy_scout_policy}</span>
            <span className="inline-pill">Doc Harvest {policy.doc_harvest_policy}</span>
            {showTestPolicy ? <span className="inline-pill">Tests {policy.test_policy}</span> : null}
            {showRequirementsClarificationMode ? (
              <span className="inline-pill">Clarification {policy.requirements_clarification_mode}</span>
            ) : null}
          </div>
        </div>

        <div className="advanced-disclosure">
          <button
            className="advanced-disclosure-toggle"
            onClick={() => setShowPolicyTuning((current) => !current)}
            aria-expanded={showPolicyTuning}
            type="button"
          >
            <div>
              <strong>Tune This Run</strong>
              <p>Adjust workflow behavior only when this run should differ from the defaults.</p>
            </div>
            <span className={`chevron${showPolicyTuning ? " expanded" : ""}`} aria-hidden="true" />
          </button>
          {showPolicyTuning ? (
            <div className="advanced-disclosure-body">
              <p className="path-label compact-note">
                Leave these at their defaults unless this run needs a different quality or clarification policy.
              </p>
              {showTestPolicy ? (
                <div className="form-section-compact">
                  <label className="form-field">
                    <span>Test Policy</span>
                    <select
                      className="select-input"
                      onChange={(event) => updatePolicy("test_policy", event.target.value as SessionPolicyValue)}
                      title={POLICY_DESCRIPTIONS.test_policy}
                      value={policy.test_policy}
                    >
                      {POLICY_OPTIONS.map((value) => (
                        <option key={value} value={value}>
                          {POLICY_OPTION_LABELS[value]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : null}

              <div className="followup-form-grid">
                <label className="form-field">
                  <span>Self Review</span>
                  <select
                    className="select-input"
                    onChange={(event) => updatePolicy("self_review_policy", event.target.value as SessionPolicyValue)}
                    title={POLICY_DESCRIPTIONS.self_review_policy}
                    value={policy.self_review_policy}
                  >
                    {POLICY_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {POLICY_OPTION_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="form-field">
                  <span>Boy Scout</span>
                  <select
                    className="select-input"
                    onChange={(event) => updatePolicy("boy_scout_policy", event.target.value as SessionPolicyValue)}
                    title={POLICY_DESCRIPTIONS.boy_scout_policy}
                    value={policy.boy_scout_policy}
                  >
                    {POLICY_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {POLICY_OPTION_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="form-section-compact">
                <label className="form-field">
                  <span>Doc Harvest</span>
                  <select
                    className="select-input"
                    onChange={(event) => updatePolicy("doc_harvest_policy", event.target.value as SessionPolicyValue)}
                    title={POLICY_DESCRIPTIONS.doc_harvest_policy}
                    value={policy.doc_harvest_policy}
                  >
                    {POLICY_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {POLICY_OPTION_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {showRequirementsClarificationMode ? (
                <div className="form-section-compact">
                  <label className="form-field">
                    <span>Requirements Clarification</span>
                    <select
                      className="select-input"
                      onChange={(event) =>
                        updatePolicy(
                          "requirements_clarification_mode",
                          event.target.value as RequirementsClarificationMode,
                        )
                      }
                      title={CLARIFICATION_MODE_DESCRIPTIONS[policy.requirements_clarification_mode]}
                      value={policy.requirements_clarification_mode}
                    >
                      {REQUIREMENTS_CLARIFICATION_OPTIONS.map((value) => (
                        <option key={value} value={value}>
                          {REQUIREMENTS_CLARIFICATION_LABELS[value]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {runtimeCapabilities !== null ? (
          <div className="advanced-disclosure">
            <button
              className="advanced-disclosure-toggle"
              onClick={() => setShowAdvancedRoleConfig((current) => !current)}
              aria-expanded={showAdvancedRoleConfig}
              type="button"
            >
              <div>
                <strong>Advanced Runtime Overrides</strong>
                <p>Change lane runner, model, or effort for this session only.</p>
              </div>
              <div className="advanced-disclosure-meta">
                <small>{effectiveRoleNames.length} lanes · {enabledOptionalLaneCount} optional enabled</small>
                <span className={`chevron${showAdvancedRoleConfig ? " expanded" : ""}`} aria-hidden="true" />
              </div>
            </button>
            {showAdvancedRoleConfig ? (
              <div className="advanced-disclosure-body artifact-stack">
                <p className="path-label">
                  These values start from the project defaults. Change them only when this session needs a specific lane override.
                </p>
                {effectiveRoleNames.map((roleName) => {
                  const current = roleConfig[roleName] ?? { runner: "", model: "", effort: "" };
                  const runnerCapability = runtimeCapabilities.runners.find(
                    (item) => item.runner === current.runner,
                  );
                  const models = runnerCapability?.models ?? [];
                  const modelCapability = models.find((item) => item.id === current.model) ?? null;

                  return (
                    <article className="artifact-card" key={roleName}>
                      <div className="artifact-meta">
                        <span>{roleName}</span>
                        <strong>{roleDisplayName(roleName)} · {current.runner || "unconfigured"}</strong>
                      </div>

                      <label className="form-field">
                        <span>Runner</span>
                        <select
                          className="select-input"
                          onChange={(event) =>
                            updateRoleConfig(roleName, { runner: event.target.value, model: "", effort: "" })
                          }
                          value={current.runner}
                        >
                          {runtimeCapabilities.availableRunners.map((runnerName) => (
                            <option key={`${roleName}-${runnerName}`} value={runnerName}>
                              {runnerName}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="form-field">
                        <span>Model</span>
                        <select
                          className="select-input"
                          onChange={(event) => updateRoleConfig(roleName, { model: event.target.value, effort: "" })}
                          value={current.model}
                        >
                          {models.map((model) => (
                            <option key={`${roleName}-${model.id}`} value={model.id}>
                              {model.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="form-field">
                        <span>Effort</span>
                        <select
                          className="select-input"
                          onChange={(event) => updateRoleConfig(roleName, { effort: event.target.value })}
                          value={current.effort}
                        >
                          {(modelCapability?.supportedEfforts ?? []).map((effort) => (
                            <option key={`${roleName}-${current.model}-${effort}`} value={effort}>
                              {effort}
                            </option>
                          ))}
                        </select>
                      </label>
                    </article>
                  );
                })}
              </div>
            ) : null}
          </div>
        ) : null}

        <button
          className="action-button action-button-strong"
          disabled={busy || normalizedTaskKey.length === 0}
          title="Create the task session, prepare the snapshot, and route the first workflow step automatically."
          type="submit"
        >
          {busy ? "Starting…" : "Create And Prepare"}
        </button>

        {error ? <p className="error-banner">{error}</p> : null}
      </form>
    </section>
  );
}
