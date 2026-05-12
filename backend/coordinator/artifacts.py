"""Artifact registration helpers."""

from __future__ import annotations

from pathlib import Path


def artifact_group_id(task_key: str, stage_name: str, attempt_number: int) -> str:
    return f"{task_key}-{stage_name}-{attempt_number}"


def write_text_artifact(
    artifacts_root: Path,
    task_key: str,
    stage_name: str,
    filename: str,
    content: str,
) -> Path:
    artifact_dir = artifacts_root / task_key / stage_name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / filename
    artifact_path.write_text(content)
    return artifact_path
