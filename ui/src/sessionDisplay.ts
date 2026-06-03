import type {
  RequirementsClarificationMode,
  SessionPolicyEntry,
  SessionPolicyValue,
  WorkflowProfile,
} from "./types";

const WORKFLOW_PROFILE_LABELS: Record<WorkflowProfile, string> = {
  oneshot: "One-shot",
  bug_full: "Bug Flow",
  story_full: "Story Flow",
};

const SESSION_STATUS_LABELS: Record<string, string> = {
  created: "Created",
  active: "In Progress",
  waiting_for_operator: "Waiting For Operator",
  paused: "Paused",
  completed: "Completed",
};

const SESSION_POLICY_LABELS: Record<string, string> = {
  test_policy: "Test Policy",
  self_review_policy: "Self Review",
  boy_scout_policy: "Code Scout",
  doc_harvest_policy: "Docs Writer",
  requirements_clarification_mode: "Requirements Clarification",
};

const POLICY_VALUE_LABELS: Record<SessionPolicyValue, string> = {
  disabled: "Disabled",
  enabled: "Enabled",
  required: "Required",
};

const CLARIFICATION_MODE_LABELS: Record<RequirementsClarificationMode, string> = {
  "ask-a-lot": "Ask A Lot",
  "ask-selectively": "Ask Selectively",
  autonomous: "Autonomous",
};

export function workflowProfileDisplayName(workflowProfile: WorkflowProfile): string {
  return WORKFLOW_PROFILE_LABELS[workflowProfile] ?? workflowProfile;
}

export function sessionStatusDisplayName(status: string | null | undefined): string {
  if (!status) {
    return "Unknown";
  }
  return SESSION_STATUS_LABELS[status] ?? status;
}

export function sessionPolicyLabel(key: string): string {
  return SESSION_POLICY_LABELS[key] ?? key;
}

export function sessionPolicyValueLabel(value: SessionPolicyEntry): string {
  if (value in POLICY_VALUE_LABELS) {
    return POLICY_VALUE_LABELS[value as SessionPolicyValue];
  }
  if (value in CLARIFICATION_MODE_LABELS) {
    return CLARIFICATION_MODE_LABELS[value as RequirementsClarificationMode];
  }
  return value;
}
