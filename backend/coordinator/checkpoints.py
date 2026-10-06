"""Checkpoint registration helpers."""

from __future__ import annotations


def checkpoint_label(task_key: str, stage_name: str, attempt_number: int) -> str:
    return f"{task_key}:{stage_name}:attempt-{attempt_number}"
