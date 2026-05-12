"""Artifact API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.api.schemas import ArtifactResponse, ArtifactsResponse
from backend.dependencies import AppDependencies

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=ArtifactsResponse)
def list_artifacts(
    session_id: int = Query(...),
    dependencies: AppDependencies = Depends(get_dependencies),
) -> ArtifactsResponse:
    artifacts = dependencies.artifact_repository.list_for_session(session_id)
    return ArtifactsResponse(
        items=[
            ArtifactResponse(
                id=artifact.id,
                session_id=artifact.session_id,
                role_id=artifact.role_id,
                stage_name=artifact.stage_name,
                artifact_type=artifact.artifact_type,
                path=artifact.path,
            )
            for artifact in artifacts
        ]
    )
