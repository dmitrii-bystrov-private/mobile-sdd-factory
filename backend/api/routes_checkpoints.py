"""Checkpoint API routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])


@router.get("")
def list_checkpoints() -> dict[str, list]:
    return {"items": []}
