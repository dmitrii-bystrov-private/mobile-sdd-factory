export type WorkflowProfile = "oneshot" | "bug_full" | "story_full";
export type SessionPolicyValue = "disabled" | "enabled" | "required";
export type RequirementsClarificationMode = "ask-a-lot" | "ask-selectively" | "autonomous";
export type SessionPolicyEntry = SessionPolicyValue | RequirementsClarificationMode;

export type Session = {
  id: number;
  task_key: string;
  task_title?: string | null;
  jira_url?: string | null;
  status: string;
  current_stage: string;
  current_owner: string | null;
  workflow_profile: WorkflowProfile;
  policy: Record<string, SessionPolicyEntry>;
  role_config: Record<string, { runner: string; model: string; effort: string }>;
};

export type Role = {
  id: number;
  session_id: number;
  role_name: string;
  status: string;
  runtime_backend: string;
  runtime_handle: string | null;
};

export type EventItem = {
  id: number;
  session_id: number;
  event_type: string;
  producer_type: string;
  producer_id?: string | null;
  payload: Record<string, unknown>;
  correlation_id?: string | null;
  created_at: string;
};

export type StreamEventPayload = {
  session_id: number;
  payload: Record<string, unknown>;
};

export type Artifact = {
  id: number;
  session_id: number;
  role_id?: number | null;
  stage_name: string;
  artifact_type: string;
  path: string;
  metadata?: Record<string, unknown> | null;
};

export type ArtifactDetail = Artifact & {
  content?: string | null;
};

export type WorkItem = {
  id: number;
  session_id: number;
  work_type: string;
  title: string;
  status: string;
  owner_role_id?: number | null;
  source_event_id?: number | null;
  priority: number;
};

export type FollowupContext = {
  source: "mr" | "qa";
  eventId: number;
  eventType: string;
  stageName: string;
  artifactType: string;
  artifactDetail: ArtifactDetail | null;
  eventPayload: Record<string, unknown>;
};

export type PlanningStepStatus = "completed" | "active" | "pending";

export type PlanningStepSummary = {
  stageName: string;
  label: string;
  status: PlanningStepStatus;
  artifactType: string | null;
  artifactDetail: ArtifactDetail | null;
};

export type PlanningSummary = {
  stageCount: number;
  completedCount: number;
  currentStage: string | null;
  steps: PlanningStepSummary[];
};

export type InteractiveStateSummary = {
  available: boolean;
  roleName: string | null;
  currentStage: string | null;
  summary: string | null;
  details: string | null;
  sourceEventType: string | null;
  sourceReason: string | null;
  needsOperatorInput: boolean;
  resumeStrategy: string | null;
};

export type RuntimeRoleStateSummary = {
  roleName: string;
  status: string;
  runtimeBackend: string;
  runtimeHandle: string | null;
  tmuxAttachCommand: string | null;
  tmuxCaptureCommand: string | null;
};

export type RuntimeAutoRecoveryStateSummary = {
  roleName: string | null;
  currentStage: string | null;
  runtimeHandle: string | null;
  deadRuntimeHandle: string | null;
  eventId: number;
  createdAt: string;
};

export type RuntimeSessionStateSummary = {
  available: boolean;
  runtimeSessionId: string | null;
  tmuxSocketPath: string | null;
  tmuxAttachCommand: string | null;
  lastAutoRecovery: RuntimeAutoRecoveryStateSummary | null;
  roles: RuntimeRoleStateSummary[];
};

export type EnvironmentDoctorCheck = {
  id: string;
  category: string;
  label: string;
  required: boolean;
  status: string;
  details: string;
  value?: string | null;
  source?: string | null;
  hint?: string | null;
};

export type EnvironmentDoctorSummary = {
  overallStatus: string;
  repoRoot: string;
  requiredOk: number;
  requiredTotal: number;
  optionalWarnings: number;
  checks: EnvironmentDoctorCheck[];
};

export type BootstrapGuidanceItem = {
  id: string;
  label: string;
  status: string;
  details: string;
  hint?: string | null;
};

export type BootstrapGuidanceSummary = {
  overallStatus: string;
  requiredActionCount: number;
  optionalActionCount: number;
  nextStep: string;
  launchCommand: string;
  backendUrl: string;
  uiUrl: string;
  requiredActions: BootstrapGuidanceItem[];
  optionalActions: BootstrapGuidanceItem[];
};

export type RuntimeCapabilityModel = {
  id: string;
  label: string;
  supportedEfforts: string[];
  defaultEffort: string | null;
  visibility: string;
  supportedInApi: boolean;
  source: string;
};

export type RunnerCapability = {
  runner: string;
  available: boolean;
  source: string;
  path: string | null;
  supportsCustomModel: boolean;
  models: RuntimeCapabilityModel[];
};

export type RoleBaseline = {
  roleName: string;
  model: string | null;
  effort: string | null;
  mcpServers: string[];
  source: string;
};

export type RuntimeCapabilitiesSummary = {
  availableRunners: string[];
  defaultRunner: string | null;
  runners: RunnerCapability[];
  roleDefaults: RoleBaseline[];
};

export type RuntimeRoleDefaultConfig = {
  runner: string | null;
  model: string | null;
  effort: string | null;
};

export type RuntimeDefaultsSummary = {
  defaultRunner: string | null;
  roleDefaults: Record<string, RuntimeRoleDefaultConfig>;
  policyDefaults: Record<string, Record<string, SessionPolicyEntry>>;
  knownRoles: string[];
  sourcePath: string;
};

export type JiraSubtasksSummary = {
  available: boolean;
  totalCount: number;
  items: Array<{
    key: string;
    title: string | null;
    status: string | null;
    queuePosition: number | null;
    isCurrent: boolean;
  }>;
};

export type SubtaskGraphRow = {
  key: string;
  issueType: string;
  title: string;
  status: string;
};

export type SubtaskGraphSummary = {
  available: boolean;
  totalCount: number;
  completedCount: number;
  unresolvedCount: number;
  rows: SubtaskGraphRow[];
};

export type SubtaskProgressItem = {
  workItemId: number;
  key: string | null;
  title: string;
  status: string;
  queuePosition: number;
};

export type SubtaskProgressSummary = {
  available: boolean;
  currentSubtaskKey: string | null;
  currentSubtaskTitle: string | null;
  totalCount: number;
  completedCount: number;
  remainingCount: number;
  items: SubtaskProgressItem[];
};

export type SessionBundle = {
  roles: Role[];
  artifacts: Artifact[];
  events: EventItem[];
  workItems: WorkItem[];
  followupContext: FollowupContext | null;
  planningSummary: PlanningSummary | null;
  interactiveStateSummary: InteractiveStateSummary | null;
  runtimeStateSummary: RuntimeSessionStateSummary | null;
  jiraSubtasksSummary: JiraSubtasksSummary | null;
  subtaskGraphSummary: SubtaskGraphSummary | null;
  subtaskProgressSummary: SubtaskProgressSummary | null;
};
