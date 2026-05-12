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


class ArtifactResponse(BaseModel):
    id: int
    session_id: int
    role_id: int | None = None
    stage_name: str
    artifact_type: str
    path: str


class ArtifactsResponse(BaseModel):
    items: list[ArtifactResponse]


class HealthResponse(BaseModel):
    status: str
