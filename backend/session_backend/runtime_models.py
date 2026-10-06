"""Runtime-facing models for long-lived role processes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeSessionHandle:
    session_id: str


@dataclass(slots=True)
class RuntimeRoleHandle:
    role_id: str
    session_id: str
    backend_name: str


@dataclass(slots=True)
class RuntimeOutputChunk:
    role_id: str
    text: str
