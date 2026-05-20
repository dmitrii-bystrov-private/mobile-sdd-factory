"""Session API routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.schemas import (
    ActiveRuntimeOutputResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    InteractiveStateSummaryResponse,
    RuntimeSessionStateResponse,
    PrepareSessionRequest,
    PrepareSessionResponse,
    JiraSubtasksSummaryResponse,
    SessionResponse,
    SessionsResponse,
    SubtaskGraphSummaryResponse,
    SubtaskProgressSummaryResponse,
)
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


def _session_task_title(workdir_root: Path, task_key: str) -> str | None:
    description_path = workdir_root / task_key / "description.md"
    if not description_path.exists():
        return None
    try:
        for raw_line in description_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("Title: "):
                title = line[len("Title: ") :].strip()
                return title or None
    except OSError:
        return None
    return None


def _session_jira_url(task_key: str) -> str:
    jira_base = os.environ.get("JIRA_BASE_URL", "https://pnlfintech.atlassian.net/browse/")
    normalized = jira_base.rstrip("/")
    return f"{normalized}/{task_key}"


def _session_workdir_root(dependencies: AppDependencies | None) -> Path | None:
    if dependencies is None:
        return None
    if getattr(dependencies, "config", None) is not None:
        return dependencies.config.workdir_root
    coordinator = getattr(dependencies, "coordinator_service", None)
    if coordinator is not None:
        return getattr(coordinator, "workdir_root", None)
    return None


def to_session_response(session, dependencies: AppDependencies | None = None) -> SessionResponse:
    task_title = None
    workdir_root = _session_workdir_root(dependencies)
    if workdir_root is not None:
        task_title = _session_task_title(workdir_root, session.task_key)
    return SessionResponse(
        id=session.id,
        task_key=session.task_key,
        task_title=task_title,
        jira_url=_session_jira_url(session.task_key),
        status=session.status.value,
        current_stage=session.current_stage,
        current_owner=session.current_owner,
        workflow_profile=session.workflow_profile,
        policy=session.policy or {},
        role_config=session.role_config or {},
    )


@router.get("", response_model=SessionsResponse)
def list_sessions(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SessionsResponse:
    sessions = dependencies.session_repository.list_all()
    return SessionsResponse(items=[to_session_response(session, dependencies) for session in sessions])


@router.post("", response_model=CreateSessionResponse)
def create_session(
    payload: CreateSessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CreateSessionResponse:
    policy = payload.policy.model_dump(exclude_none=True) if payload.policy else None
    role_config = (
        {
            role_name: config.model_dump(exclude_none=True)
            for role_name, config in payload.role_config.items()
        }
        if payload.role_config
        else None
    )
    try:
        if payload.prepare:
            session, event, created, details = dependencies.coordinator_service.prepare_task_session(
                raw_task_key=payload.task_key,
                workflow_profile=payload.workflow_profile,
                policy=policy,
                role_config=role_config,
            )
        else:
            session, event, created = dependencies.coordinator_service.create_task_session(
                task_key=payload.task_key,
                workflow_profile=payload.workflow_profile,
                policy=policy,
                role_config=role_config,
            )
            details = {
                "resolved_task_key": None,
                "issue_type": None,
                "readiness": None,
                "snapshot_exit_code": None,
                "followup_event_type": None,
            }
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreateSessionResponse(
        created=created,
        session=to_session_response(session, dependencies),
        event_type=event.event_type,
        resolved_task_key=(
            str(details["resolved_task_key"]) if details["resolved_task_key"] is not None else None
        ),
        issue_type=str(details["issue_type"]) if details["issue_type"] is not None else None,
        readiness=str(details["readiness"]) if details["readiness"] is not None else None,
        snapshot_exit_code=(
            int(details["snapshot_exit_code"]) if details["snapshot_exit_code"] is not None else None
        ),
        followup_event_type=(
            str(details["followup_event_type"])
            if details["followup_event_type"] is not None
            else None
        ),
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


@router.get("/{session_id}/subtask-progress", response_model=SubtaskProgressSummaryResponse)
def get_subtask_progress(
    session_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SubtaskProgressSummaryResponse:
    try:
        summary = dependencies.coordinator_service.get_subtask_progress_summary(session_id)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SubtaskProgressSummaryResponse(**summary)


@router.get("/{session_id}/jira-subtasks", response_model=JiraSubtasksSummaryResponse)
def get_jira_subtasks(
    session_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> JiraSubtasksSummaryResponse:
    try:
        summary = dependencies.coordinator_service.get_created_jira_subtasks_summary(session_id)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JiraSubtasksSummaryResponse(**summary)


@router.get("/{session_id}/interactive-state", response_model=InteractiveStateSummaryResponse)
def get_interactive_state(
    session_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> InteractiveStateSummaryResponse:
    try:
        summary = dependencies.coordinator_service.get_interactive_state_summary(session_id)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InteractiveStateSummaryResponse(**summary)


@router.get("/{session_id}/runtime-state", response_model=RuntimeSessionStateResponse)
def get_runtime_state(
    session_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RuntimeSessionStateResponse:
    try:
        summary = dependencies.coordinator_service.get_runtime_state_summary(session_id)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RuntimeSessionStateResponse(**summary)


@router.get("/{session_id}/active-runtime-output", response_model=ActiveRuntimeOutputResponse)
def get_active_runtime_output(
    session_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> ActiveRuntimeOutputResponse:
    try:
        summary = dependencies.coordinator_service.get_active_runtime_output_summary(session_id)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActiveRuntimeOutputResponse(**summary)


@router.post("/prepare", response_model=PrepareSessionResponse, include_in_schema=False)
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
        session=to_session_response(session, dependencies),
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
