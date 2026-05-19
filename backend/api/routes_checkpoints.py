"""Checkpoint API routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])


@router.get("", include_in_schema=False)
def list_checkpoints() -> dict[str, list]:
    return {"items": []}
