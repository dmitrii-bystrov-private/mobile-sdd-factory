"""Artifact API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.api.schemas import ArtifactDetailResponse, ArtifactResponse, ArtifactsResponse
from backend.dependencies import AppDependencies
from backend.state.artifact_repository import DEFAULT_UI_EXCLUDED_ARTIFACT_TYPES

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def get_dependencies(request: Request) -> AppDependencies:
    return request.app.state.dependencies


@router.get("", response_model=ArtifactsResponse)
def list_artifacts(
    session_id: int = Query(...),
    include_telemetry: bool = Query(default=True),
    dependencies: AppDependencies = Depends(get_dependencies),
) -> ArtifactsResponse:
    artifacts = (
        dependencies.artifact_repository.list_for_session(session_id)
        if include_telemetry
        else dependencies.artifact_repository.list_for_session_excluding(
            session_id,
            DEFAULT_UI_EXCLUDED_ARTIFACT_TYPES,
        )
    )
    return ArtifactsResponse(
        items=[
            ArtifactResponse(
                id=artifact.id,
                session_id=artifact.session_id,
                role_id=artifact.role_id,
                stage_name=artifact.stage_name,
                artifact_type=artifact.artifact_type,
                path=artifact.path,
                metadata=artifact.metadata,
            )
            for artifact in artifacts
        ]
    )


@router.get("/{artifact_id}", response_model=ArtifactDetailResponse)
def get_artifact(
    artifact_id: int,
    dependencies: AppDependencies = Depends(get_dependencies),
) -> ArtifactDetailResponse:
    artifact = dependencies.artifact_repository.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} was not found")

    content: str | None = None
    artifact_path = Path(artifact.path)
    if artifact_path.exists() and artifact_path.is_file():
        content = artifact_path.read_text()

    return ArtifactDetailResponse(
        id=artifact.id,
        session_id=artifact.session_id,
        role_id=artifact.role_id,
        stage_name=artifact.stage_name,
        artifact_type=artifact.artifact_type,
        path=artifact.path,
        metadata=artifact.metadata,
        content=content,
    )
