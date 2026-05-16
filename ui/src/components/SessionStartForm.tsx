import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import type { RuntimeCapabilitiesSummary, SessionPolicyValue, WorkflowProfile } from "../types";

type SessionStartFormProps = {
  onCreated: (sessionId: number) => Promise<void>;
  runtimeCapabilities: RuntimeCapabilitiesSummary | null;
};

const POLICY_OPTIONS: SessionPolicyValue[] = ["disabled", "enabled", "required"];

type DraftPolicy = {
  test_policy: SessionPolicyValue;
  self_review_policy: SessionPolicyValue;
  boy_scout_policy: SessionPolicyValue;
  doc_harvest_policy: SessionPolicyValue;
};

function defaultDraftPolicy(): DraftPolicy {
  return {
    test_policy: "enabled",
    self_review_policy: "enabled",
    boy_scout_policy: "enabled",
    doc_harvest_policy: "enabled",
  };
}

export function SessionStartForm({
  onCreated,
  runtimeCapabilities,
}: SessionStartFormProps): JSX.Element {
  const [taskKey, setTaskKey] = useState("");
  const [workflowProfile, setWorkflowProfile] = useState<WorkflowProfile>("oneshot");
  const [policy, setPolicy] = useState<DraftPolicy>(defaultDraftPolicy());
  const [roleConfig, setRoleConfig] = useState<Record<string, { runner: string; model: string; effort: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showTestPolicy = workflowProfile === "bug_full";
  const normalizedTaskKey = taskKey.trim().toUpperCase();

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
    return {
      workflow_profile: workflowProfile,
      policy: basePolicy,
    };
  }, [policy, workflowProfile]);

  const effectiveRoleNames = useMemo(() => {
    const roleNames = ["task-coordinator", "implementer", "verification-coordinator"];
    if (workflowProfile === "bug_full") {
      roleNames.push("bug-fixer");
    }
    if (policy.self_review_policy !== "disabled") {
      roleNames.push("code-reviewer");
    }
    return roleNames;
  }, [policy.self_review_policy, workflowProfile]);

  useEffect(() => {
    if (runtimeCapabilities === null) {
      return;
    }

    const runnerIndex = new Map(runtimeCapabilities.runners.map((runner) => [runner.runner, runner]));
    const legacyIndex = new Map(runtimeCapabilities.legacyRoleDefaults.map((item) => [item.roleName, item]));
    const defaultRunner = runtimeCapabilities.defaultRunner ?? runtimeCapabilities.availableRunners[0] ?? "claude";

    function defaultConfigForRole(roleName: string): { runner: string; model: string; effort: string } {
      const runner = defaultRunner;
      const runnerCapability = runnerIndex.get(runner);
      const legacyDefault = legacyIndex.get(roleName);
      const models = runnerCapability?.models ?? [];
      const model =
        legacyDefault?.model ??
        (runner === "claude" ? models.find((item) => item.id === "sonnet")?.id : undefined) ??
        models[0]?.id ??
        "";
      const modelCapability = models.find((item) => item.id === model);
      const effort =
        legacyDefault?.effort ??
        modelCapability?.defaultEffort ??
        modelCapability?.supportedEfforts[0] ??
        "medium";
      return { runner, model, effort };
    }

    setRoleConfig((current) => {
      const next: Record<string, { runner: string; model: string; effort: string }> = {};
      for (const roleName of effectiveRoleNames) {
        next[roleName] = current[roleName] ?? defaultConfigForRole(roleName);
      }
      return next;
    });
  }, [effectiveRoleNames, runtimeCapabilities]);

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
        policy: payload.policy,
        role_config: roleConfig,
      });
      const prepared = await apiClient.prepareSession(normalizedTaskKey);
      await onCreated(prepared.session.id ?? created.session.id);
      setTaskKey("");
      setWorkflowProfile("oneshot");
      setPolicy(defaultDraftPolicy());
      setRoleConfig({});
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
            <option value="oneshot">oneshot</option>
            <option value="bug_full">bug_full</option>
            <option value="story_full">story_full</option>
          </select>
        </label>

        {showTestPolicy ? (
          <label className="form-field">
            <span>Test Policy</span>
            <select
              className="select-input"
              onChange={(event) => updatePolicy("test_policy", event.target.value as SessionPolicyValue)}
              value={policy.test_policy}
            >
              {POLICY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <label className="form-field">
          <span>Self Review</span>
          <select
            className="select-input"
            onChange={(event) => updatePolicy("self_review_policy", event.target.value as SessionPolicyValue)}
            value={policy.self_review_policy}
          >
            {POLICY_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <label className="form-field">
          <span>Boy Scout</span>
          <select
            className="select-input"
            onChange={(event) => updatePolicy("boy_scout_policy", event.target.value as SessionPolicyValue)}
            value={policy.boy_scout_policy}
          >
            {POLICY_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <label className="form-field">
          <span>Doc Harvest</span>
          <select
            className="select-input"
            onChange={(event) => updatePolicy("doc_harvest_policy", event.target.value as SessionPolicyValue)}
            value={policy.doc_harvest_policy}
          >
            {POLICY_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        {runtimeCapabilities !== null ? (
          <div className="artifact-stack">
            <p className="eyebrow">Role Runtime Config</p>
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
                    <strong>{current.runner || "unconfigured"}</strong>
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

        <button
          className="action-button action-button-strong"
          disabled={busy || normalizedTaskKey.length === 0}
          type="submit"
        >
          {busy ? "Starting…" : "Create And Prepare"}
        </button>

        {error ? <p className="error-banner">{error}</p> : null}
      </form>
    </section>
  );
}
