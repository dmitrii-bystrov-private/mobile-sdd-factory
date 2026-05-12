"""Shared lifecycle enums for backend domain models."""

from enum import StrEnum


class SessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    WAITING_FOR_OPERATOR = "waiting_for_operator"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RoleStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    FAILED = "failed"


class WorkItemStatus(StrEnum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    WAITING_FOR_OPERATOR = "waiting_for_operator"
    COMPLETED = "completed"


class VerificationStatus(StrEnum):
    REQUESTED = "requested"
    PASSED = "passed"
    FAILED = "failed"

