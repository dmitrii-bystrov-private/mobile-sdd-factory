#!/usr/bin/env python3
"""Validate a real Codex quality loop through persistent reviewer and verifier roles."""

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
    *,
    dependencies,
    target_stage: str,
    timeout_seconds: float = 360.0,
):
    deadline = time.time() + timeout_seconds
    last_response = None
    while time.time() < deadline:
        dependencies.loop_runner.run_once()
        for worker_role_name in ("implementer", "code-reviewer", "verification-coordinator"):
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
        if response.session.current_stage == target_stage:
            return response
        time.sleep(1.0)
    assert last_response is not None
    return last_response


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    build_acceptance_dependencies = _load_build_acceptance_dependencies(repo_root)

    with managed_run_root(repo_root, "sdd-factory-real-codex-quality-loop") as temp_root:
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = f"IOS-ACCEPT-REAL-CODEX-QUALITY-{temp_root.name.split('.')[-1].upper()}"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="oneshot",
                prepare=True,
                policy={
                    "self_review_policy": "required",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
                role_config=acceptance_role_config(
                    ["implementer", "code-reviewer", "verification-coordinator"],
                    runner_overrides={
                        "implementer": "codex",
                        "code-reviewer": "codex",
                        "verification-coordinator": "codex",
                    },
                ),
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id
        assert create_response.followup_event_type == "implementation_requested"

        first_verification = wait_for_stage(
            session_id=session_id,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert first_verification.session.current_stage == "verification_requested"
        assert first_verification.session.status == "active"

        inject_event(
            InjectEventRequest(
                session_id=session_id,
                event_type="verification_failed",
                payload={"summary": "verification failed", "failures": ["lint"]},
            ),
            dependencies=deps,
        )

        second_verification = wait_for_stage(
            session_id=session_id,
            dependencies=deps,
            target_stage="verification_requested",
        )
        assert second_verification.session.current_stage == "verification_requested"
        assert second_verification.session.status == "active"

        events = list_events(session_id=session_id, dependencies=deps).items
        event_types = [item.event_type for item in events]
        assert "self_review_requested" in event_types
        assert "self_review_passed" in event_types
        assert event_types.count("verification_requested") >= 2
        assert event_types.count("implementation_completed") >= 2
        assert "verification_failed" in event_types

        shutdown_dependencies(deps)
        print(f"Real codex quality loop validation passed for session {session_id}.")


if __name__ == "__main__":
    main()
