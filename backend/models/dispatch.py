"""Dispatch lifecycle models for routed role handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models.enums import DispatchStatus


@dataclass(slots=True)
class Dispatch:
    id: int | None
    session_id: int
    role_id: int
    work_item_id: int
    stage_name: str
    dispatch_token: str
    hydration_version: int
    runtime_handle: str | None
    status: DispatchStatus
    error_text: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
