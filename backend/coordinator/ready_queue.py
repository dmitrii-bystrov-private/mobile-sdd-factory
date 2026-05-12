"""Deterministic ready-queue helpers."""

from __future__ import annotations

from backend.models.work_item import WorkItem


def next_ready_item(items: list[WorkItem]) -> WorkItem | None:
    """Pick the highest-priority work item from already-derived candidates."""

    if not items:
        return None
    return sorted(items, key=lambda item: item.priority, reverse=True)[0]
