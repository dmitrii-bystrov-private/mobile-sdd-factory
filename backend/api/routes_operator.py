"""Operator action routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.routes_sessions import to_session_response
from backend.api.schemas import (
    IngestMrCommentsRequest,
    IngestMrCommentsResponse,
    ReopenFromQaRequest,
    ReopenFromQaResponse,
    RedirectSessionRequest,
    RedirectSessionResponse,
    LoopRunnerControlResponse,
    LoopRunnerStatusResponse,
    PauseSessionRequest,
    PauseSessionResponse,
    PollSessionOutputRequest,
    PollSessionOutputResponse,
    RetrySessionRequest,
    RetrySessionResponse,
    ResumeSessionRequest,
    ResumeSessionResponse,
    RunLoopOnceResponse,
)
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/operator", tags=["operator"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.post("/pause-session", response_model=PauseSessionResponse)
def pause_session(
    payload: PauseSessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> PauseSessionResponse:
    try:
        session, event = dependencies.coordinator_service.pause_session(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PauseSessionResponse(
        paused=True,
        session=to_session_response(session),
        event_type=event.event_type,
    )


@router.post("/resume-session", response_model=ResumeSessionResponse)
def resume_session(
    payload: ResumeSessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> ResumeSessionResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.resume_session(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ResumeSessionResponse(
        resumed=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type,
    )


@router.post("/retry-session", response_model=RetrySessionResponse)
def retry_session(
    payload: RetrySessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RetrySessionResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.retry_session(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RetrySessionResponse(
        retried=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type,
    )


@router.post("/redirect-session", response_model=RedirectSessionResponse)
def redirect_session(
    payload: RedirectSessionRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RedirectSessionResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.redirect_session(
            session_id=payload.session_id,
            target_role_name=payload.target_role_name,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectSessionResponse(
        redirected=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type,
    )


@router.post("/ingest-mr-comments", response_model=IngestMrCommentsResponse)
def ingest_mr_comments(
    payload: IngestMrCommentsRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> IngestMrCommentsResponse:
    try:
        session, event, followup_event, discussion_count = (
            dependencies.coordinator_service.ingest_mr_comments(
                session_id=payload.session_id,
                platform=payload.platform,
                mr_id=payload.mr_id,
            )
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestMrCommentsResponse(
        ingested=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
        discussion_count=discussion_count,
    )


@router.post("/reopen-from-qa", response_model=ReopenFromQaResponse)
def reopen_from_qa(
    payload: ReopenFromQaRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> ReopenFromQaResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.reopen_from_qa(
            session_id=payload.session_id,
            comment_text=payload.comment_text,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReopenFromQaResponse(
        reopened=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
    )


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


def to_loop_status_response(status) -> LoopRunnerStatusResponse:
    return LoopRunnerStatusResponse(
        running=status.running,
        interval_seconds=status.interval_seconds,
        tick_count=status.tick_count,
        last_session_count=status.last_session_count,
        last_chunk_count=status.last_chunk_count,
    )


@router.get("/loop-status", response_model=LoopRunnerStatusResponse)
def loop_status(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> LoopRunnerStatusResponse:
    return to_loop_status_response(dependencies.loop_runner.status())


@router.post("/start-loop", response_model=LoopRunnerControlResponse)
def start_loop(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> LoopRunnerControlResponse:
    changed = dependencies.loop_runner.start()
    return LoopRunnerControlResponse(
        changed=changed,
        status=to_loop_status_response(dependencies.loop_runner.status()),
    )


@router.post("/stop-loop", response_model=LoopRunnerControlResponse)
def stop_loop(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> LoopRunnerControlResponse:
    changed = dependencies.loop_runner.stop()
    return LoopRunnerControlResponse(
        changed=changed,
        status=to_loop_status_response(dependencies.loop_runner.status()),
    )
