"""Helpers for reading snapshot-produced subtask status tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SnapshotSubtask:
    key: str
    issue_type: str
    title: str
    status: str


def read_snapshot_subtasks(statuses_file: Path) -> list[SnapshotSubtask]:
    if not statuses_file.exists():
        raise FileNotFoundError(statuses_file)

    lines = statuses_file.read_text().splitlines()
    rows = [line for line in lines if line.startswith("|")]
    if len(rows) < 3:
        return []

    data_rows = rows[2:]
    subtasks: list[SnapshotSubtask] = []
    for row in data_rows[1:]:
        parts = [part.strip() for part in row.strip().strip("|").split("|")]
        if len(parts) < 4:
            continue
        key, issue_type, title, status = parts[:4]
        if not key:
            continue
        subtasks.append(
            SnapshotSubtask(
                key=key,
                issue_type=issue_type,
                title=title,
                status=status,
            )
        )
    return subtasks


def unresolved_subtasks(subtasks: list[SnapshotSubtask]) -> list[SnapshotSubtask]:
    terminal_statuses = {"ready for test", "resolved", "released"}
    return [
        subtask
        for subtask in subtasks
        if subtask.status.strip().lower() not in terminal_statuses
    ]
