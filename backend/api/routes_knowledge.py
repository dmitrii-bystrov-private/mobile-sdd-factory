"""Knowledge browsing routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.schemas import KnowledgeItemResponse, KnowledgeItemsResponse
from backend.dependencies import AppDependencies
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=KnowledgeItemsResponse)
def list_knowledge(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> KnowledgeItemsResponse:
    items = dependencies.coordinator_service.list_knowledge()
    return KnowledgeItemsResponse(
        items=[
            KnowledgeItemResponse(
                id=item.id,
                title=item.title,
                platform=item.platform,
                workflow_profiles=list(item.workflow_profiles),
                task_key=item.task_key,
                guidance=item.guidance,
                scope=item.scope,
                created_at=item.created_at,
                path=str(item.path),
            )
            for item in items
        ]
    )
