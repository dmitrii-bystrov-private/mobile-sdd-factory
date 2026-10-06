"""Role domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models.enums import RoleStatus


@dataclass(slots=True)
class Role:
    id: int | None
    session_id: int
    role_name: str
    status: RoleStatus
    runtime_backend: str
    runtime_handle: str | None = None
    last_hydration_version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
