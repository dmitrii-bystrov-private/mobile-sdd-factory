"""API request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    task_key: str


class SessionResponse(BaseModel):
    id: int
    task_key: str
    status: str
    current_stage: str
    current_owner: str | None = None


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


class ResumeSessionRequest(BaseModel):
    session_id: int


class ResumeSessionResponse(BaseModel):
    resumed: bool
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
