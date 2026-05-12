"""Operator action routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/operator", tags=["operator"])


@router.post("/pause")
def pause_session() -> dict[str, str]:
    return {"status": "not_implemented"}
