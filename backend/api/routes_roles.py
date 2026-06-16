"""Role API routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.api.routes_sessions import to_session_response
from backend.api.schemas import (
    CollectRoleOutputRequest,
    CollectRoleOutputResponse,
    RoleOutputRequest,
    RoleOutputResponse,
    RoleResponse,
    RolesResponse,
    SubmitRoleResultRequest,
    SubmitRoleResultResponse,
)
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies
from backend.roles.contracts import RETIRED_ROLE_NAMES

router = APIRouter(prefix="/roles", tags=["roles"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=RolesResponse)
def list_roles(
    session_id: int = Query(...),
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RolesResponse:
    roles = [
        role
        for role in dependencies.role_repository.list_for_session(session_id)
        if role.role_name not in RETIRED_ROLE_NAMES
    ]
    return RolesResponse(
        items=[
            RoleResponse(
                id=role.id,
                session_id=role.session_id,
                role_name=role.role_name,
                status=role.status.value,
                runtime_backend=role.runtime_backend,
                runtime_handle=role.runtime_handle,
            )
            for role in roles
        ]
    )


@router.post("/output", response_model=RoleOutputResponse, include_in_schema=False)
def submit_role_output(
    payload: RoleOutputRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RoleOutputResponse:
    try:
        session, mapped_event, followup_event = dependencies.coordinator_service.handle_role_output(
            session_id=payload.session_id,
            role_name=payload.role_name,
            output_type=payload.output_type,
            payload=payload.payload,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RoleOutputResponse(
        accepted=True,
        mapped_event_type=mapped_event.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
        session=to_session_response(session),
    )


@router.post("/collect-output", response_model=CollectRoleOutputResponse, include_in_schema=False)
def collect_role_output(
    payload: CollectRoleOutputRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CollectRoleOutputResponse:
    try:
        session, event, chunk_count = dependencies.coordinator_service.collect_role_output(
            session_id=payload.session_id,
            role_name=payload.role_name,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CollectRoleOutputResponse(
        collected=chunk_count > 0,
        session=to_session_response(session),
        chunk_count=chunk_count,
        event_type=event.event_type if event else None,
    )


@router.post("/submit-result", response_model=SubmitRoleResultResponse, include_in_schema=False)
def submit_role_result(
    payload: SubmitRoleResultRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SubmitRoleResultResponse:
    try:
        session, event, mapped_event_type, followup_event_type, ignored = (
            dependencies.coordinator_service.submit_role_result_document(
                document={
                    "output_type": payload.output_type,
                    "payload": payload.payload,
                }
            )
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Transient backend persistence failure while accepting the terminal role result. "
                "Retry the same write-result helper call."
            ),
        ) from exc

    return SubmitRoleResultResponse(
        accepted=True,
        ignored=ignored,
        event_type=event.event_type,
        mapped_event_type=mapped_event_type,
        followup_event_type=followup_event_type,
        session=to_session_response(session),
    )
