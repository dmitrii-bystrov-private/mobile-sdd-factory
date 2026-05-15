"""Knowledge browsing routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.api.schemas import KnowledgeItemResponse, KnowledgeItemsResponse
from backend.dependencies import AppDependencies
from backend.knowledge.store import KnowledgeStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=KnowledgeItemsResponse)
def list_knowledge(
    dependencies: AppDependencies = Depends(get_dependencies),
) -> KnowledgeItemsResponse:
    knowledge_root = dependencies.coordinator_service.knowledge_root
    if knowledge_root is None:
        return KnowledgeItemsResponse(items=[])
    knowledge_store = KnowledgeStore(knowledge_root)
    items = knowledge_store.list_items()
    return KnowledgeItemsResponse(
        items=[
            KnowledgeItemResponse(
                id=item.id,
                title=item.title,
                source_type=item.source_type,
                platform=item.platform,
                workflow_profiles=list(item.workflow_profiles),
                task_key=item.task_key,
                guidance=item.guidance,
                scope=item.scope,
                source_summary=item.source_summary,
                created_at=item.created_at,
                path=str(item.path),
            )
            for item in items
        ]
    )
