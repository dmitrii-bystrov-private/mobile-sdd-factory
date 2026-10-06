"""Work item API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.api.schemas import WorkItemResponse, WorkItemsResponse
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/work-items", tags=["work-items"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=WorkItemsResponse)
def list_work_items(
    session_id: int = Query(...),
    dependencies: AppDependencies = Depends(get_dependencies),
) -> WorkItemsResponse:
    work_items = dependencies.work_item_repository.list_for_session(session_id)
    return WorkItemsResponse(
        items=[
            WorkItemResponse(
                id=item.id,
                session_id=item.session_id,
                work_type=item.work_type,
                title=item.title,
                status=item.status.value,
                owner_role_id=item.owner_role_id,
                source_event_id=item.source_event_id,
                priority=item.priority,
            )
            for item in work_items
        ]
    )
