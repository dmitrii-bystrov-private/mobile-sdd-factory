import { useMemo, useState } from "react";

import { apiClient } from "../api/client";
import type { SessionPolicyValue, WorkflowProfile } from "../types";

type SessionStartFormProps = {
  onCreated: (sessionId: number) => Promise<void>;
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
}: SessionStartFormProps): JSX.Element {
  const [taskKey, setTaskKey] = useState("");
  const [workflowProfile, setWorkflowProfile] = useState<WorkflowProfile>("oneshot");
  const [policy, setPolicy] = useState<DraftPolicy>(defaultDraftPolicy());
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
      });
      const prepared = await apiClient.prepareSession(normalizedTaskKey);
      await onCreated(prepared.session.id ?? created.session.id);
      setTaskKey("");
      setWorkflowProfile("oneshot");
      setPolicy(defaultDraftPolicy());
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
