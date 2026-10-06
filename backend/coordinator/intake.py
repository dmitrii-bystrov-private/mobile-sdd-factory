"""Task intake gate skeleton."""

from __future__ import annotations


class IntakeError(RuntimeError):
    """Raised when deterministic intake/setup fails."""


def classify_task_readiness(task_key: str, issue_type: str) -> str:
    """Classify whether a task is ready for execution.

    Placeholder until real intake rules are implemented.
    """

    del task_key, issue_type
    return "ready_for_execution"
