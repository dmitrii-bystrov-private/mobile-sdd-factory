#!/usr/bin/env python3
"""Validate live runtime stop/restart management against tmux-hosted roles."""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

from backend.api.routes_operator import (
    restart_runtime_role,
    restart_runtime_session,
    stop_runtime_role,
    stop_runtime_session,
)
from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import (
    CollectRoleOutputRequest,
    CreateSessionRequest,
    PrepareSessionRequest,
    RestartRuntimeRoleRequest,
    RestartRuntimeSessionRequest,
    StopRuntimeRoleRequest,
    StopRuntimeSessionRequest,
)
from backend.roles.contracts import IMPLEMENTER_ROLE
from run_roots import managed_run_root, shutdown_dependencies


def _load_build_acceptance_dependencies(repo_root: Path):
    probe_path = repo_root / "factory" / "acceptance" / "run-real-launcher-tmux-probe.py"
    spec = importlib.util.spec_from_file_location("real_launcher_tmux_probe", probe_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load probe module from {probe_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_acceptance_dependencies


def wait_for_stage(
    session_id: int,
    role_name: str,
    *,
    dependencies,
    target_stage: str,
    timeout_seconds: float = 150.0,
) -> tuple[object, str]:
    deadline = time.time() + timeout_seconds
    last_response = None
    output_text = ""
    role = dependencies.role_repository.get_by_name(session_id, role_name)
    role_id = role.id if role is not None else None
    while time.time() < deadline:
        dependencies.loop_runner.run_once()
        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=session_id,
                role_name=role_name,
            ),
            dependencies=dependencies,
        )
        last_response = response
        artifacts = dependencies.artifact_repository.list_for_session(session_id)
        runtime_outputs = [
            item
            for item in artifacts
            if item.artifact_type == "runtime_output" and item.role_id == role_id
        ]
        if runtime_outputs:
            output_path = Path(runtime_outputs[-1].path)
            if output_path.is_file():
                output_text = output_path.read_text()
        if response.session.current_stage == target_stage:
            return response, output_text
        time.sleep(0.5)
    assert last_response is not None
    return last_response, output_text


def _runner_name() -> str:
    return os.environ.get("SDD_FACTORY_ACCEPTANCE_RUNNER", "claude").strip() or "claude"


def _create_prepared_session(*, task_key: str, dependencies) -> int:
    runner = _runner_name()
    role_config = None
    if runner != "claude":
        role_config = {
            "implementer": {
                "runner": runner,
                "model": "gpt-5.5",
                "effort": "medium",
            },
            "verification-coordinator": {
                "runner": runner,
                "model": "gpt-5.5",
                "effort": "medium",
            },
        }
    create_response = create_session(
        CreateSessionRequest(
            task_key=task_key,
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
            role_config=role_config,
        ),
        dependencies=dependencies,
    )
    session_id = create_response.session.id
    prepare_response = prepare_session(
        PrepareSessionRequest(task_key=task_key),
        dependencies=dependencies,
    )
    assert prepare_response.followup_event_type == "implementation_requested"
    return session_id


def _print_runtime_debug_bundle(*, session_id: int, dependencies) -> None:
    try:
        summary = dependencies.coordinator_service.get_runtime_state_summary(session_id)
    except Exception as exc:  # pragma: no cover - debug-only path
        print(f"Unable to read runtime state for session {session_id}: {exc}")
        return
    print(f"\n[debug] session_id={session_id}")
    print(f"[debug] runtime_session_id={summary.get('runtime_session_id')}")
    if summary.get("tmux_socket_path"):
        print(f"[debug] tmux_socket_path={summary['tmux_socket_path']}")
    if summary.get("tmux_attach_command"):
        print(f"[debug] tmux_attach_command={summary['tmux_attach_command']}")
    for role in summary.get("roles", []):
        print(
            f"[debug] role={role.get('role_name')} status={role.get('status')} "
            f"handle={role.get('runtime_handle')}"
        )
        if role.get("tmux_attach_command"):
            print(f"[debug]   attach={role['tmux_attach_command']}")
        if role.get("tmux_capture_command"):
            print(f"[debug]   capture={role['tmux_capture_command']}")


def _validate_role_restart(*, session_id: int, dependencies) -> None:
    before = dependencies.coordinator_service.get_runtime_state_summary(session_id)
    before_runtime_session_id = before["runtime_session_id"]
    before_role = next(item for item in before["roles"] if item["role_name"] == IMPLEMENTER_ROLE)
    before_handle = before_role["runtime_handle"]
    assert before_handle is not None

    stopped = stop_runtime_role(
        StopRuntimeRoleRequest(session_id=session_id, role_name=IMPLEMENTER_ROLE),
        dependencies=dependencies,
    )
    assert stopped.stopped
    assert stopped.event_type == "runtime_role_stopped_by_operator"
    assert stopped.session.status == "paused"

    restarted = restart_runtime_role(
        RestartRuntimeRoleRequest(session_id=session_id, role_name=IMPLEMENTER_ROLE),
        dependencies=dependencies,
    )
    assert restarted.restarted
    assert restarted.event_type == "runtime_role_restarted_by_operator"
    assert restarted.followup_event_type == "role_input_dispatched"
    assert restarted.session.status == "active"

    after = dependencies.coordinator_service.get_runtime_state_summary(session_id)
    after_role = next(item for item in after["roles"] if item["role_name"] == IMPLEMENTER_ROLE)
    assert after["runtime_session_id"] == before_runtime_session_id
    assert after_role["runtime_handle"] is not None
    assert after_role["runtime_handle"] == before_handle

    response, output_text = wait_for_stage(
        session_id=session_id,
        role_name=IMPLEMENTER_ROLE,
        dependencies=dependencies,
        target_stage="verification_requested",
    )
    assert response.session.current_stage == "verification_requested", output_text[-12000:]


def _validate_session_restart(*, session_id: int, dependencies) -> None:
    before = dependencies.coordinator_service.get_runtime_state_summary(session_id)
    before_runtime_session_id = before["runtime_session_id"]
    before_handles = {
        item["role_name"]: item["runtime_handle"]
        for item in before["roles"]
    }

    stopped = stop_runtime_session(
        StopRuntimeSessionRequest(session_id=session_id),
        dependencies=dependencies,
    )
    assert stopped.stopped
    assert stopped.event_type == "runtime_session_stopped_by_operator"
    assert stopped.session.status == "paused"

    restarted = restart_runtime_session(
        RestartRuntimeSessionRequest(session_id=session_id),
        dependencies=dependencies,
    )
    assert restarted.restarted
    assert restarted.event_type == "runtime_session_restarted_by_operator"
    assert restarted.followup_event_type == "role_input_dispatched"
    assert restarted.session.status == "active"

    after = dependencies.coordinator_service.get_runtime_state_summary(session_id)
    assert before_runtime_session_id is not None
    assert after["runtime_session_id"] is not None
    after_handles = {item["role_name"]: item["runtime_handle"] for item in after["roles"]}
    assert after_handles[IMPLEMENTER_ROLE] is not None
    assert before_handles[IMPLEMENTER_ROLE] is not None

    response, output_text = wait_for_stage(
        session_id=session_id,
        role_name=IMPLEMENTER_ROLE,
        dependencies=dependencies,
        target_stage="verification_requested",
    )
    assert response.session.current_stage == "verification_requested", output_text[-12000:]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    build_acceptance_dependencies = _load_build_acceptance_dependencies(repo_root)
    with managed_run_root(repo_root, "sdd-factory-runtime-management") as temp_root:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)
        role_session_id: int | None = None
        session_session_id: int | None = None
        try:
            role_task_key = f"IOS-ACCEPT-RUNTIME-ROLE-{temp_root.name.split('.')[-1].upper()}"
            role_session_id = _create_prepared_session(task_key=role_task_key, dependencies=deps)
            _validate_role_restart(session_id=role_session_id, dependencies=deps)

            session_task_key = f"IOS-ACCEPT-RUNTIME-SESSION-{temp_root.name.split('.')[-1].upper()}"
            session_session_id = _create_prepared_session(task_key=session_task_key, dependencies=deps)
            _validate_session_restart(session_id=session_session_id, dependencies=deps)

            shutdown_dependencies(deps)
            print("Runtime management acceptance passed.")
        except Exception:
            print(f"\n[debug] acceptance temp_root={temp_root}")
            if role_session_id is not None:
                _print_runtime_debug_bundle(session_id=role_session_id, dependencies=deps)
            if session_session_id is not None:
                _print_runtime_debug_bundle(session_id=session_session_id, dependencies=deps)
            print("[debug] temp root preserved for inspection")
            raise


if __name__ == "__main__":
    main()
