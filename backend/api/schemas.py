"""API request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SessionPolicyPayload(BaseModel):
    test_policy: str | None = None
    self_review_policy: str | None = None
    boy_scout_policy: str | None = None
    doc_harvest_policy: str | None = None


class RoleRuntimeConfigPayload(BaseModel):
    runner: str | None = None
    model: str | None = None
    effort: str | None = None


class CreateSessionRequest(BaseModel):
    task_key: str
    workflow_profile: str
    policy: SessionPolicyPayload | None = None
    role_config: dict[str, RoleRuntimeConfigPayload] | None = None


class SessionResponse(BaseModel):
    id: int
    task_key: str
    status: str
    current_stage: str
    current_owner: str | None = None
    workflow_profile: str
    policy: dict[str, str]
    role_config: dict[str, dict[str, str]]


class CreateSessionResponse(BaseModel):
    created: bool
    session: SessionResponse
    event_type: str


class PrepareSessionRequest(BaseModel):
    task_key: str


class PrepareSessionResponse(BaseModel):
    created: bool
    session: SessionResponse
    event_type: str
    resolved_task_key: str
    issue_type: str
    readiness: str
    snapshot_exit_code: int
    followup_event_type: str | None = None


class SessionsResponse(BaseModel):
    items: list[SessionResponse]


class SubtaskGraphRowResponse(BaseModel):
    key: str
    issue_type: str
    title: str
    status: str


class SubtaskGraphSummaryResponse(BaseModel):
    available: bool
    total_count: int
    completed_count: int
    unresolved_count: int
    rows: list[SubtaskGraphRowResponse]


class SubtaskProgressItemResponse(BaseModel):
    work_item_id: int
    key: str | None = None
    title: str
    status: str
    queue_position: int


class SubtaskProgressSummaryResponse(BaseModel):
    available: bool
    current_subtask_key: str | None = None
    current_subtask_title: str | None = None
    total_count: int
    completed_count: int
    remaining_count: int
    items: list[SubtaskProgressItemResponse]


class JiraSubtaskItemResponse(BaseModel):
    key: str
    title: str | None = None
    status: str | None = None
    queue_position: int | None = None
    is_current: bool = False


class JiraSubtasksSummaryResponse(BaseModel):
    available: bool
    total_count: int
    items: list[JiraSubtaskItemResponse]


class InteractiveStateSummaryResponse(BaseModel):
    available: bool
    role_name: str | None = None
    current_stage: str | None = None
    summary: str | None = None
    details: str | None = None
    source_event_type: str | None = None
    needs_operator_input: bool = False


class RuntimeRoleStateResponse(BaseModel):
    role_name: str
    status: str
    runtime_backend: str
    runtime_handle: str | None = None
    tmux_attach_command: str | None = None
    tmux_capture_command: str | None = None


class RuntimeAutoRecoveryStateResponse(BaseModel):
    role_name: str | None = None
    current_stage: str | None = None
    runtime_handle: str | None = None
    dead_runtime_handle: str | None = None
    event_id: int
    created_at: str


class RuntimeSessionStateResponse(BaseModel):
    available: bool
    runtime_session_id: str | None = None
    tmux_socket_path: str | None = None
    tmux_attach_command: str | None = None
    last_auto_recovery: RuntimeAutoRecoveryStateResponse | None = None
    roles: list[RuntimeRoleStateResponse]


class EnvironmentDoctorCheckResponse(BaseModel):
    id: str
    category: str
    label: str
    required: bool
    status: str
    details: str
    value: str | None = None
    source: str | None = None
    hint: str | None = None


class EnvironmentDoctorResponse(BaseModel):
    overall_status: str
    repo_root: str
    required_ok: int
    required_total: int
    optional_warnings: int
    checks: list[EnvironmentDoctorCheckResponse]


class BootstrapGuidanceItemResponse(BaseModel):
    id: str
    label: str
    status: str
    details: str
    hint: str | None = None


class BootstrapGuidanceResponse(BaseModel):
    overall_status: str
    required_action_count: int
    optional_action_count: int
    next_step: str
    launch_command: str
    backend_url: str
    ui_url: str
    required_actions: list[BootstrapGuidanceItemResponse]
    optional_actions: list[BootstrapGuidanceItemResponse]


class RuntimeCapabilityModelResponse(BaseModel):
    id: str
    label: str
    supported_efforts: list[str]
    default_effort: str | None = None
    visibility: str
    supported_in_api: bool
    source: str


class RunnerCapabilityResponse(BaseModel):
    runner: str
    available: bool
    source: str
    path: str | None = None
    supports_custom_model: bool
    models: list[RuntimeCapabilityModelResponse]


class LegacyRoleDefaultResponse(BaseModel):
    role_name: str
    model: str | None = None
    effort: str | None = None
    mcp_servers: list[str]
    source: str


class RuntimeCapabilitiesResponse(BaseModel):
    available_runners: list[str]
    default_runner: str | None = None
    runners: list[RunnerCapabilityResponse]
    legacy_role_defaults: list[LegacyRoleDefaultResponse]


class RuntimeRoleDefaultConfigResponse(BaseModel):
    runner: str | None = None
    model: str | None = None
    effort: str | None = None


class RuntimeDefaultsResponse(BaseModel):
    default_runner: str | None = None
    role_defaults: dict[str, RuntimeRoleDefaultConfigResponse]
    known_roles: list[str]
    source_path: str


class RuntimeRoleDefaultConfigPayload(BaseModel):
    runner: str | None = None
    model: str | None = None
    effort: str | None = None


class UpdateRuntimeDefaultsRequest(BaseModel):
    default_runner: str | None = None
    role_defaults: dict[str, RuntimeRoleDefaultConfigPayload]


class RoleResponse(BaseModel):
    id: int
    session_id: int
    role_name: str
    status: str
    runtime_backend: str
    runtime_handle: str | None = None


class RolesResponse(BaseModel):
    items: list[RoleResponse]


class RoleOutputRequest(BaseModel):
    session_id: int
    role_name: str
    output_type: str
    payload: dict = {}


class RoleOutputResponse(BaseModel):
    accepted: bool
    mapped_event_type: str
    followup_event_type: str | None = None
    session: SessionResponse


class CollectRoleOutputRequest(BaseModel):
    session_id: int
    role_name: str


class CollectRoleOutputResponse(BaseModel):
    collected: bool
    session: SessionResponse
    chunk_count: int
    event_type: str | None = None


class EventResponse(BaseModel):
    id: int
    session_id: int
    event_type: str
    producer_type: str
    producer_id: str | None = None
    payload: dict
    correlation_id: str | None = None


class EventsResponse(BaseModel):
    items: list[EventResponse]


class ArtifactResponse(BaseModel):
    id: int
    session_id: int
    role_id: int | None = None
    stage_name: str
    artifact_type: str
    path: str
    metadata: dict | None = None


class ArtifactsResponse(BaseModel):
    items: list[ArtifactResponse]


class ArtifactDetailResponse(BaseModel):
    id: int
    session_id: int
    role_id: int | None = None
    stage_name: str
    artifact_type: str
    path: str
    metadata: dict
    content: str | None = None


class KnowledgeItemResponse(BaseModel):
    id: str
    title: str
    platform: str
    workflow_profiles: list[str]
    task_key: str
    guidance: str
    scope: str | None = None
    created_at: str
    path: str


class KnowledgeItemsResponse(BaseModel):
    items: list[KnowledgeItemResponse]


class WorkItemResponse(BaseModel):
    id: int
    session_id: int
    work_type: str
    title: str
    status: str
    owner_role_id: int | None = None
    source_event_id: int | None = None
    priority: int


class WorkItemsResponse(BaseModel):
    items: list[WorkItemResponse]


class InjectEventRequest(BaseModel):
    session_id: int
    event_type: str
    payload: dict = {}


class InjectEventResponse(BaseModel):
    accepted: bool
    event_type: str
    followup_event_type: str | None = None
    session: SessionResponse


class PollSessionOutputRequest(BaseModel):
    session_id: int


class PollSessionOutputResponse(BaseModel):
    polled: bool
    session: SessionResponse
    role_count: int
    chunk_count: int
    event_type: str | None = None


class PauseSessionRequest(BaseModel):
    session_id: int


class PauseSessionResponse(BaseModel):
    paused: bool
    session: SessionResponse
    event_type: str


class ResumeSessionRequest(BaseModel):
    session_id: int


class ResumeSessionResponse(BaseModel):
    resumed: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class SendOperatorRuntimeInputRequest(BaseModel):
    session_id: int
    text: str


class SendOperatorRuntimeInputResponse(BaseModel):
    sent: bool
    session: SessionResponse
    event_type: str


class RetrySessionRequest(BaseModel):
    session_id: int


class RetrySessionResponse(BaseModel):
    retried: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class RedirectSessionRequest(BaseModel):
    session_id: int
    target_role_name: str


class RedirectSessionResponse(BaseModel):
    redirected: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class StopRuntimeRoleRequest(BaseModel):
    session_id: int
    role_name: str


class StopRuntimeRoleResponse(BaseModel):
    stopped: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class RestartRuntimeRoleRequest(BaseModel):
    session_id: int
    role_name: str


class RestartRuntimeRoleResponse(BaseModel):
    restarted: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class StopRuntimeSessionRequest(BaseModel):
    session_id: int


class StopRuntimeSessionResponse(BaseModel):
    stopped: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class RestartRuntimeSessionRequest(BaseModel):
    session_id: int


class RestartRuntimeSessionResponse(BaseModel):
    restarted: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class CleanupTaskRequest(BaseModel):
    session_id: int
    cleanup_mode: str
    force: bool = False


class CleanupTaskResponse(BaseModel):
    cleaned: bool
    deleted_session: bool
    cleanup_mode: str
    task_key: str
    jira_status: str | None = None
    full_cleanup_allowed: bool
    removed_paths: list[str]
    session: SessionResponse | None = None


class IngestMrCommentsRequest(BaseModel):
    session_id: int
    platform: str
    mr_id: str


class IngestMrCommentsResponse(BaseModel):
    ingested: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None
    discussion_count: int


class CreateMrRequest(BaseModel):
    session_id: int


class CreateMrResponse(BaseModel):
    handed_off: bool
    session: SessionResponse
    event_type: str
    mr_url: str | None = None


class SendToTestRequest(BaseModel):
    session_id: int


class SendToTestResponse(BaseModel):
    handed_off: bool
    session: SessionResponse
    event_type: str


class StartSubtaskGraphRequest(BaseModel):
    session_id: int


class StartSubtaskGraphResponse(BaseModel):
    started: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str


class CreateSubtasksFromPlanRequest(BaseModel):
    session_id: int


class CreateSubtasksFromPlanResponse(BaseModel):
    created: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class RefreshSubtaskStateRequest(BaseModel):
    session_id: int


class RefreshSubtaskStateResponse(BaseModel):
    refreshed: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class CreateKnowledgeRequest(BaseModel):
    session_id: int
    title: str
    guidance: str
    scope: str | None = None


class CreateKnowledgeResponse(BaseModel):
    created: bool
    session: SessionResponse
    event_type: str


class CompleteDocHarvestRequest(BaseModel):
    session_id: int
    summary: str


class CompleteDocHarvestResponse(BaseModel):
    completed: bool
    session: SessionResponse
    event_type: str


class CompleteSelfReviewRequest(BaseModel):
    session_id: int
    outcome: str
    summary: str


class CompleteSelfReviewResponse(BaseModel):
    completed: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class ReopenFromQaRequest(BaseModel):
    session_id: int
    comment_text: str


class ReopenFromQaResponse(BaseModel):
    reopened: bool
    session: SessionResponse
    event_type: str
    followup_event_type: str | None = None


class RunLoopOnceResponse(BaseModel):
    ran: bool
    session_count: int
    chunk_count: int
    event_type: str | None = None


class LoopRunnerStatusResponse(BaseModel):
    running: bool
    interval_seconds: float
    tick_count: int
    last_session_count: int
    last_chunk_count: int


class LoopRunnerControlResponse(BaseModel):
    changed: bool
    status: LoopRunnerStatusResponse


class HealthResponse(BaseModel):
    status: str
