#!/usr/bin/env python3
"""Validate that a real launcher-backed implementer reaches an interactive auth blocker."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import time

from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, get_interactive_state, prepare_session
from backend.api.schemas import CollectRoleOutputRequest, CreateSessionRequest, PrepareSessionRequest
from backend.roles.contracts import IMPLEMENTER_ROLE


def load_real_launcher_probe_module():
    module_path = Path(__file__).resolve().parent / "run-real-launcher-pty-probe.py"
    spec = spec_from_file_location("real_launcher_pty_probe", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    real_launcher_probe = load_real_launcher_probe_module()

    with tempfile.TemporaryDirectory(prefix="sdd-factory-real-interactive-auth.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = real_launcher_probe.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-REAL-INTERACTIVE-AUTH-001"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="oneshot",
                policy={
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
            ),
            dependencies=deps,
        )
        session_id = create_response.session.id
        prepare_session(
            PrepareSessionRequest(task_key=task_key),
            dependencies=deps,
        )

        role = deps.role_repository.get_by_name(session_id, IMPLEMENTER_ROLE)
        saw_ready = False
        deadline = time.time() + 30.0
        last_summary = None
        while time.time() < deadline:
            response = collect_role_output(
                CollectRoleOutputRequest(
                    session_id=session_id,
                    role_name=IMPLEMENTER_ROLE,
                ),
                dependencies=deps,
            )
            if deps.session_backend.pty_role_ready.get(role.runtime_handle, False):
                saw_ready = True

            state = get_interactive_state(session_id, dependencies=deps)
            last_summary = state.summary if state.available else None
            if response.session.status == "waiting_for_operator" and state.available:
                assert state.summary == "interactive auth required", state
                assert state.needs_operator_input is True, state
                assert saw_ready, "expected live launcher to become ready before auth blocker"
                print(f"Real interactive auth acceptance passed for session {session_id}.")
                return
            time.sleep(1.0)

        raise AssertionError(
            f"timed out waiting for real interactive auth blocker; saw_ready={saw_ready} last_summary={last_summary!r}"
        )


if __name__ == "__main__":
    main()
