"""Role API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.api.schemas import RoleResponse, RolesResponse
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/roles", tags=["roles"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=RolesResponse)
def list_roles(
    session_id: int = Query(...),
    dependencies: AppDependencies = Depends(get_dependencies),
) -> RolesResponse:
    roles = dependencies.role_repository.list_for_session(session_id)
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
