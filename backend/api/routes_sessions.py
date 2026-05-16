"""Session API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    PrepareSessionRequest,
    PrepareSessionResponse,
    SessionResponse,
    SessionsResponse,
    SubtaskGraphSummaryResponse,
)
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


def to_session_response(session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        task_key=session.task_key,
        status=session.status.value,
        current_stage=session.current_stage,
        current_owner=session.current_owner,
        workflow_profile=session.workflow_profile,
        policy=session.policy or {},
    )


@router.get("", response_model=SessionsResponse)
def list_sessions(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SessionsResponse:
    sessions = dependencies.session_repository.list_all()
    return SessionsResponse(items=[to_session_response(session) for session in sessions])


@router.post("", response_model=CreateSessionResponse)
def create_session(
    payload: CreateSessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CreateSessionResponse:
    try:
        session, event, created = dependencies.coordinator_service.create_task_session(
            task_key=payload.task_key,
            workflow_profile=payload.workflow_profile,
            policy=payload.policy.model_dump(exclude_none=True) if payload.policy else None,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreateSessionResponse(
        created=created,
        session=to_session_response(session),
        event_type=event.event_type,
    )


@router.get("/{session_id}/subtask-graph", response_model=SubtaskGraphSummaryResponse)
def get_subtask_graph(
    session_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SubtaskGraphSummaryResponse:
    try:
        summary = dependencies.coordinator_service.get_subtask_graph_summary(session_id)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SubtaskGraphSummaryResponse(**summary)


@router.post("/prepare", response_model=PrepareSessionResponse)
def prepare_session(
    payload: PrepareSessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> PrepareSessionResponse:
    try:
        session, event, created, details = dependencies.coordinator_service.prepare_task_session(
            raw_task_key=payload.task_key
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PrepareSessionResponse(
        created=created,
        session=to_session_response(session),
        event_type=event.event_type,
        resolved_task_key=str(details["resolved_task_key"]),
        issue_type=str(details["issue_type"]),
        readiness=str(details["readiness"]),
        snapshot_exit_code=int(details["snapshot_exit_code"]),
        followup_event_type=(
            str(details["followup_event_type"])
            if details["followup_event_type"] is not None
            else None
        ),
    )
