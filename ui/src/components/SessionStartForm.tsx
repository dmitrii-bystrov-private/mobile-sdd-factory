import { useEffect, useMemo, useRef, useState } from "react";

import { apiClient } from "../api/client";
import { useToast } from "./ToastProvider";
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

const TASK_KEY_PATTERN = /^(IOS|ANDR)-\d+$/i;
const TASK_KEY_EXTRACT_PATTERN = /\b(IOS|ANDR)-\d+\b/i;

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

function normalizeTaskKeyInput(value: string): string {
  const trimmed = value.trim();
  const extracted = trimmed.match(TASK_KEY_EXTRACT_PATTERN)?.[0];
  return (extracted ?? trimmed).toUpperCase();
}

export function SessionStartForm({
  onCreated,
  runtimeCapabilities,
  runtimeDefaults,
}: SessionStartFormProps): JSX.Element {
  const { showToast, showActivity, clearActivity } = useToast();
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
  const normalizedTaskKey = normalizeTaskKeyInput(taskKey);
  const hasTaskKeyInput = normalizedTaskKey.length > 0;
  const isTaskKeyValid = !hasTaskKeyInput || TASK_KEY_PATTERN.test(normalizedTaskKey);

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
    if (!TASK_KEY_PATTERN.test(normalizedTaskKey)) {
      setError("Use a Jira key like IOS-1234 or ANDR-5678");
      return;
    }

    setBusy(true);
    setError(null);
    showActivity("Preparing new workflow…");
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
      const message = err instanceof Error ? err.message : "Failed to start session";
      setError(message);
      showToast(message, "error");
    } finally {
      clearActivity();
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
    <section className="panel panel-sidebar sidebar-zone sidebar-zone-start">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Start Session</p>
          <h2>New Workflow</h2>
        </div>
      </div>

      <form className="session-start-form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="form-field">
          <span>Task Key</span>
          <input
            className="text-input"
            onChange={(event) => setTaskKey(normalizeTaskKeyInput(event.target.value))}
            placeholder="IOS-1234 or Jira link"
            value={taskKey}
          />
        </label>
        {hasTaskKeyInput && !isTaskKeyValid ? (
          <p className="form-help form-help-error">Enter a valid Jira task key.</p>
        ) : null}

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

        <div className="advanced-disclosure">
          <button
            className="advanced-disclosure-toggle"
            onClick={() => setShowPolicyTuning((current) => !current)}
            aria-expanded={showPolicyTuning}
            type="button"
          >
            <div>
              <strong>Workflow policies</strong>
              <p>Change optional lanes and clarification behavior for this run only.</p>
            </div>
            <div className="advanced-disclosure-meta">
              <span className={`chevron${showPolicyTuning ? " expanded" : ""}`} aria-hidden="true" />
            </div>
          </button>
          {showPolicyTuning ? (
            <div className="advanced-disclosure-body">
              {showTestPolicy ? (
                <div className="form-section-compact">
                  <label className="form-field">
                    <span>Test Policy</span>
                    <select
                      className="select-input"
                      onChange={(event) => updatePolicy("test_policy", event.target.value as SessionPolicyValue)}
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
                  <span>Code Scout</span>
                    <select
                      className="select-input"
                      onChange={(event) => updatePolicy("boy_scout_policy", event.target.value as SessionPolicyValue)}
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
                  <span>Docs Writer</span>
                  <select
                    className="select-input"
                    onChange={(event) => updatePolicy("doc_harvest_policy", event.target.value as SessionPolicyValue)}
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
                <strong>Lane runtime overrides</strong>
                <p>Override runner, model, or effort for specific lanes in this run.</p>
              </div>
              <div className="advanced-disclosure-meta">
                <span className={`chevron${showAdvancedRoleConfig ? " expanded" : ""}`} aria-hidden="true" />
              </div>
            </button>
            {showAdvancedRoleConfig ? (
              <div className="advanced-disclosure-body artifact-stack">
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
                        <strong>{roleName}</strong>
                        <span>{current.runner || "unconfigured"}</span>
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

        <div className="session-start-actions">
          <button
            className="action-button action-button-strong"
            disabled={busy || normalizedTaskKey.length === 0 || !isTaskKeyValid}
            title="Create the task session, prepare the snapshot, and route the first workflow step automatically."
            type="submit"
          >
            {busy ? "Starting run…" : "Start run"}
          </button>

          {error ? <p className="error-banner">{error}</p> : null}
        </div>
      </form>
    </section>
  );
}
