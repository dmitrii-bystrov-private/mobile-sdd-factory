"""Event routing skeleton for coordinator-owned orchestration."""

from __future__ import annotations


def route_event(event_type: str) -> str:
    """Return the next high-level coordinator action for an event."""

    mapping = {
        "task_started": "run_intake",
        "implementation_requested": "dispatch_implementer",
        "verification_requested": "run_verification",
        "verification_failed": "request_fix",
        "task_completed": "finalize_session",
    }
    return mapping.get(event_type, "noop")
