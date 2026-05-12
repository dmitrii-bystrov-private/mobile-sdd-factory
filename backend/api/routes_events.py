"""Event API routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/events", tags=["events"])


@router.post("")
def inject_event() -> dict[str, str]:
    return {"status": "not_implemented"}
