"""Operator action routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.routes_sessions import to_session_response
from backend.api.schemas import PollSessionOutputRequest, PollSessionOutputResponse, RunLoopOnceResponse
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/operator", tags=["operator"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.post("/pause")
def pause_session() -> dict[str, str]:
    return {"status": "not_implemented"}


@router.post("/poll-session-output", response_model=PollSessionOutputResponse)
def poll_session_output(
    payload: PollSessionOutputRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> PollSessionOutputResponse:
    try:
        session, event, role_count, chunk_count = dependencies.coordinator_service.poll_session_output(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PollSessionOutputResponse(
        polled=chunk_count > 0,
        session=to_session_response(session),
        role_count=role_count,
        chunk_count=chunk_count,
        event_type=event.event_type if event else None,
    )


@router.post("/run-loop-once", response_model=RunLoopOnceResponse)
def run_loop_once(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RunLoopOnceResponse:
    event, session_count, chunk_count = dependencies.coordinator_service.run_loop_once()
    return RunLoopOnceResponse(
        ran=session_count > 0,
        session_count=session_count,
        chunk_count=chunk_count,
        event_type=event.event_type if event else None,
    )
