"""API request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SessionPolicyPayload(BaseModel):
    test_policy: str | None = None
    self_review_policy: str | None = None
    boy_scout_policy: str | None = None
    doc_harvest_policy: str | None = None


class CreateSessionRequest(BaseModel):
    task_key: str
    workflow_profile: str
    policy: SessionPolicyPayload | None = None


class SessionResponse(BaseModel):
    id: int
    task_key: str
    status: str
    current_stage: str
    current_owner: str | None = None
    workflow_profile: str
    policy: dict[str, str]


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
