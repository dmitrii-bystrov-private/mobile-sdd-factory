"""Deterministic role hydration helpers."""

from __future__ import annotations

from backend.models.work_item import WorkItem


def build_role_hydration(
    role_name: str,
    task_key: str,
    current_stage: str,
    active_work_item: WorkItem | None = None,
    extra_payload: dict[str, str | int | None] | None = None,
) -> dict[str, str | int | None]:
    """Build a minimal deterministic hydration payload for a role."""

    payload: dict[str, str | int | None] = {
        "role_name": role_name,
        "task_key": task_key,
        "current_stage": current_stage,
    }
    if active_work_item is not None:
        payload["work_item_id"] = active_work_item.id
        payload["work_item_title"] = active_work_item.title
        payload["work_item_type"] = active_work_item.work_type
    if extra_payload:
        payload.update(extra_payload)
    return payload
