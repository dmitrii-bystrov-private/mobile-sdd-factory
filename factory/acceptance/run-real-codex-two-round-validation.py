#!/usr/bin/env python3
"""Validate two real implementer rounds against a launcher-backed Codex role."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

from backend.api.routes_events import inject_event, list_events
from backend.api.routes_operator import poll_session_output
from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session
from backend.api.schemas import (
    CollectRoleOutputRequest,
    CreateSessionRequest,
    InjectEventRequest,
    PollSessionOutputRequest,
)
from backend.roles.contracts import IMPLEMENTER_ROLE
from runtime_config import acceptance_role_config
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
    timeout_seconds: float = 240.0,
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
        time.sleep(1.0)
    assert last_response is not None
    return last_response, output_text


def wait_for_session_stage(
    session_id: int,
    role_name: str,
    *,
    dependencies,
    target_stage: str,
    timeout_seconds: float = 240.0,
) -> tuple[object, str]:
    deadline = time.time() + timeout_seconds
    last_response = None
    output_text = ""
    role = dependencies.role_repository.get_by_name(session_id, role_name)
    role_id = role.id if role is not None else None
    while time.time() < deadline:
        dependencies.loop_runner.run_once()
        for worker_role_name in ("implementer", "verification-coordinator"):
            collect_role_output(
                CollectRoleOutputRequest(
                    session_id=session_id,
                    role_name=worker_role_name,
                ),
                dependencies=dependencies,
            )
        response = poll_session_output(
            PollSessionOutputRequest(session_id=session_id),
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
        time.sleep(1.0)
    assert last_response is not None
    return last_response, output_text


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    build_acceptance_dependencies = _load_build_acceptance_dependencies(repo_root)

    with managed_run_root(repo_root, "sdd-factory-real-codex-two-round") as temp_root:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = f"IOS-ACCEPT-REAL-CODEX-TWO-ROUND-{temp_root.name.split('.')[-1].upper()}"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="oneshot",
                prepare=True,
                policy={
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
                role_config=acceptance_role_config(
                    ["implementer", "verification-coordinator"],
                    runner_overrides={
                        "implementer": "codex",
                        "verification-coordinator": "codex",
                    },
                ),
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id
        assert create_response.followup_event_type == "implementation_requested"

        first_response, first_output = wait_for_session_stage(
            session_id=session_id,
            role_name=IMPLEMENTER_ROLE,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert first_response.session.current_stage == "verification_requested", first_output[-12000:]
        assert first_response.session.status == "active"

        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="verification_failed",
                payload={"summary": "verification failed", "failures": ["lint"]},
            ),
            dependencies=deps,
        )

        second_response, second_output = wait_for_session_stage(
            session_id=session_id,
            role_name=IMPLEMENTER_ROLE,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert second_response.session.current_stage == "verification_requested", second_output[-12000:]
        assert second_response.session.status == "active"

        events = list_events(session_id=session_id, dependencies=deps).items
        event_types = [item.event_type for item in events]
        assert event_types.count("implementation_completed") >= 2
        assert event_types.count("verification_requested") >= 2
        assert "verification_failed" in event_types

        artifacts = deps.artifact_repository.list_for_session(session_id)
        assert any(item.artifact_type == "role_result_json" for item in artifacts)

        shutdown_dependencies(deps)
        print(f"Real codex two-round validation passed for session {session_id}.")


if __name__ == "__main__":
    main()
