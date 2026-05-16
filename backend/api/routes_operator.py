"""Operator action routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.routes_sessions import to_session_response
from backend.api.schemas import (
    CompleteDocHarvestRequest,
    CompleteDocHarvestResponse,
    EnvironmentDoctorResponse,
    CreateSubtasksFromPlanRequest,
    CreateSubtasksFromPlanResponse,
    RefreshSubtaskStateRequest,
    RefreshSubtaskStateResponse,
    CreateKnowledgeRequest,
    CreateKnowledgeResponse,
    CompleteSelfReviewRequest,
    CompleteSelfReviewResponse,
    CreateMrRequest,
    CreateMrResponse,
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
    SendOperatorRuntimeInputRequest,
    SendOperatorRuntimeInputResponse,
    SendToTestRequest,
    SendToTestResponse,
    StartSubtaskGraphRequest,
    StartSubtaskGraphResponse,
    ResumeSessionRequest,
    ResumeSessionResponse,
    RunLoopOnceResponse,
)
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies
from factory.doctor.environment_doctor import build_report

router = APIRouter(prefix="/operator", tags=["operator"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("/environment-doctor", response_model=EnvironmentDoctorResponse)
def get_environment_doctor(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> EnvironmentDoctorResponse:
    repo_root = (
        dependencies.config.repo_root
        if dependencies.config is not None
        else Path(__file__).resolve().parents[2]
    )
    report = build_report(repo_root=repo_root)
    return EnvironmentDoctorResponse(**report)


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


@router.post("/send-runtime-input", response_model=SendOperatorRuntimeInputResponse)
def send_runtime_input(
    payload: SendOperatorRuntimeInputRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SendOperatorRuntimeInputResponse:
    try:
        session, event = dependencies.coordinator_service.send_operator_runtime_input(
            session_id=payload.session_id,
            text=payload.text,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SendOperatorRuntimeInputResponse(
        sent=True,
        session=to_session_response(session),
        event_type=event.event_type,
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


@router.post("/create-mr", response_model=CreateMrResponse)
def create_mr(
    payload: CreateMrRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CreateMrResponse:
    try:
        session, event, mr_url = dependencies.coordinator_service.create_mr_handoff(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CreateMrResponse(
        handed_off=True,
        session=to_session_response(session),
        event_type=event.event_type,
        mr_url=mr_url,
    )


@router.post("/complete-doc-harvest", response_model=CompleteDocHarvestResponse)
def complete_doc_harvest(
    payload: CompleteDocHarvestRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CompleteDocHarvestResponse:
    try:
        session, event = dependencies.coordinator_service.complete_doc_harvest(
            session_id=payload.session_id,
            summary=payload.summary,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CompleteDocHarvestResponse(
        completed=True,
        session=to_session_response(session),
        event_type=event.event_type,
    )


@router.post("/complete-self-review", response_model=CompleteSelfReviewResponse)
def complete_self_review(
    payload: CompleteSelfReviewRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CompleteSelfReviewResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.complete_self_review(
            session_id=payload.session_id,
            outcome=payload.outcome,
            summary=payload.summary,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CompleteSelfReviewResponse(
        completed=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
    )


@router.post("/send-to-test", response_model=SendToTestResponse)
def send_to_test(
    payload: SendToTestRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> SendToTestResponse:
    try:
        session, event = dependencies.coordinator_service.send_to_test_handoff(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SendToTestResponse(
        handed_off=True,
        session=to_session_response(session),
        event_type=event.event_type,
    )


@router.post("/start-subtask-graph", response_model=StartSubtaskGraphResponse)
def start_subtask_graph(
    payload: StartSubtaskGraphRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> StartSubtaskGraphResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.start_subtask_graph(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StartSubtaskGraphResponse(
        started=True,
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type,
    )


@router.post("/create-subtasks-from-plan", response_model=CreateSubtasksFromPlanResponse)
def create_subtasks_from_plan(
    payload: CreateSubtasksFromPlanRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CreateSubtasksFromPlanResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.create_subtasks_from_plan(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CreateSubtasksFromPlanResponse(
        created=event.event_type == "jira_subtasks_created",
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
    )


@router.post("/refresh-subtask-state", response_model=RefreshSubtaskStateResponse)
def refresh_subtask_state(
    payload: RefreshSubtaskStateRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RefreshSubtaskStateResponse:
    try:
        session, event, followup_event = dependencies.coordinator_service.refresh_subtask_state(
            session_id=payload.session_id
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RefreshSubtaskStateResponse(
        refreshed=event.event_type == "subtask_state_refreshed_by_operator",
        session=to_session_response(session),
        event_type=event.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
    )


@router.post("/create-knowledge", response_model=CreateKnowledgeResponse)
def create_knowledge(
    payload: CreateKnowledgeRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> CreateKnowledgeResponse:
    try:
        session, event = dependencies.coordinator_service.create_knowledge(
            session_id=payload.session_id,
            title=payload.title,
            guidance=payload.guidance,
            scope=payload.scope,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CreateKnowledgeResponse(
        created=True,
        session=to_session_response(session),
        event_type=event.event_type,
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
