"""Persist authoritative factory context alongside an exact native conversation."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess

from backend.roles.session_history import SessionHistoryError, atomic_json, capture


def context(service, session, role) -> dict:
    root = service.workdir_root / session.task_key
    items = service.work_item_repository.list_for_session(session.id)
    events = service.event_repository.list_for_session(session.id)
    operator_events = [{"id": event.id, "type": event.event_type, "payload": event.payload}
                       for event in events if event.producer_type == "operator"]
    files = [root / "spec/verification-strategy.json", root / "spec/e2e-verdict.json",
             root / "spec/e2e-operator-decisions.json", root / "spec/final-verification.md",
             root / "description.md", root / "statuses.md"]
    try:
        sha = subprocess.check_output(["git", "-C", str(root / "repo"), "rev-parse", "HEAD"],
                                      text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        sha = None
    return {"version": 1, "session_id": session.id, "task_key": session.task_key,
            "role_name": role.role_name, "stage": session.current_stage, "status": session.status.value,
            "owner": session.current_owner, "role_config": (session.role_config or {}).get(role.role_name),
            "source_sha": sha, "operator_event_history": operator_events,
            "work_items": [{"id": item.id, "type": item.work_type, "status": item.status.value,
                            "owner_role_id": item.owner_role_id} for item in items],
            "current_artifacts": [str(path) for path in files if path.exists()],
            "note": "HYDRATION.json and the current work item govern execution. Historical decisions apply only to their original scope and evidence; native gate binding remains required."}


def save(service, session, role) -> Path:
    workspace = service.role_workspace_manager.ensure_role_workspace(session.task_key, role.role_name)
    required = role.runtime_backend == "tmux" and role.last_hydration_version > 0
    native = capture(workspace.directory, (session.role_config or {}).get(role.role_name, {}).get("runner", ""),
                     required=required)
    record = context(service, session, role)
    record.update(saved_at=datetime.now(UTC).isoformat(), native_session=native,
                  last_hydration_version=role.last_hydration_version)
    path = workspace.directory / "RUNTIME_CHECKPOINT.json"
    atomic_json(path, record)
    return path


def refresh(service, session, role) -> Path | None:
    directory = service.role_workspace_manager.role_directory(session.task_key, role.role_name)
    checkpoint = directory / "RUNTIME_CHECKPOINT.json"
    if not checkpoint.exists():
        return None
    try:
        previous = json.loads(checkpoint.read_text())
    except ValueError as error:
        raise SessionHistoryError("Runtime checkpoint is not valid JSON") from error
    if (not isinstance(previous, dict) or previous.get("version") != 1 or previous.get("session_id") != session.id
            or previous.get("role_name") != role.role_name or previous.get("task_key") != session.task_key):
        raise SessionHistoryError("Runtime checkpoint belongs to another task or role")
    payload = context(service, session, role)
    payload["previous_checkpoint_path"] = str(checkpoint)
    payload["native_session_id"] = (previous.get("native_session") or {}).get("session_id")
    path = directory / "RESUME_CONTEXT.json"
    atomic_json(path, payload)
    return path


def main() -> None:
    from backend.dependencies import build_dependencies
    service = build_dependencies().coordinator_service
    task_key = os.environ["SDD_FACTORY_TASK_KEY"]
    session = service.session_repository.get_by_task_key(task_key)
    if session is None:
        raise RuntimeError("No factory session exists for this checkpoint")
    role = service.role_repository.get_by_name(session.id, os.environ["SDD_FACTORY_ROLE_NAME"])
    if role is None:
        raise RuntimeError("No factory role exists for this checkpoint")
    refresh(service, session, role)


if __name__ == "__main__":
    main()
