"""Event API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.api.routes_sessions import to_session_response
from backend.api.schemas import EventResponse, EventsResponse, InjectEventRequest, InjectEventResponse
from backend.coordinator.intake import IntakeError
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/events", tags=["events"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=EventsResponse)
def list_events(
    session_id: int = Query(...),
    dependencies: AppDependencies = Depends(get_dependencies),
) -> EventsResponse:
    events = dependencies.event_repository.list_for_session(session_id)
    return EventsResponse(
        items=[
            EventResponse(
                id=event.id,
                session_id=event.session_id,
                event_type=event.event_type,
                producer_type=event.producer_type,
                producer_id=event.producer_id,
                payload=event.payload,
                correlation_id=event.correlation_id,
            )
            for event in events
        ]
    )


@router.post("", response_model=InjectEventResponse)
def inject_event(
    payload: InjectEventRequest,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> InjectEventResponse:
    try:
        session, followup_event = dependencies.coordinator_service.handle_operator_event(
            session_id=payload.session_id,
            event_type=payload.event_type,
            payload=payload.payload,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return InjectEventResponse(
        accepted=True,
        event_type=payload.event_type,
        followup_event_type=followup_event.event_type if followup_event else None,
        session=to_session_response(session),
    )
