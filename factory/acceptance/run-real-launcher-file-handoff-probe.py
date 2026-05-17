#!/usr/bin/env python3
"""Probe file-backed routed work delivery for a real launcher-backed role."""

from __future__ import annotations

import importlib.util
import tempfile
import time
from pathlib import Path

from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import CollectRoleOutputRequest, CreateSessionRequest, PrepareSessionRequest


def _load_build_acceptance_dependencies(repo_root: Path):
    probe_path = repo_root / "factory" / "acceptance" / "run-real-launcher-tmux-probe.py"
    spec = importlib.util.spec_from_file_location("real_launcher_tmux_probe", probe_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load probe module from {probe_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_acceptance_dependencies


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    build_acceptance_dependencies = _load_build_acceptance_dependencies(repo_root)

    with tempfile.TemporaryDirectory(prefix="sdd-factory-real-launcher-file-handoff.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = f"IOS-ACCEPT-REAL-LAUNCHER-FILE-HANDOFF-{temp_root.name.split('.')[-1].upper()}"
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

        role = deps.role_repository.get_by_name(session_id, "implementer")
        assert role is not None
        runtime_handle = role.runtime_handle
        assert runtime_handle is not None

        role_workspace = (
            temp_root
            / "workdir"
            / task_key
            / "runtime"
            / "role-workspaces"
            / "implementer"
        )
        routed_work_path = role_workspace / "ROUTED_WORK.md"

        deadline = time.time() + 30.0
        output_text = ""
        saw_bootstrap = False
        while time.time() < deadline:
            response = collect_role_output(
                CollectRoleOutputRequest(
                    session_id=session_id,
                    role_name="implementer",
                ),
                dependencies=deps,
            )
            artifacts = deps.artifact_repository.list_for_session(session_id)
            runtime_outputs = [item for item in artifacts if item.artifact_type == "runtime_output"]
            if runtime_outputs:
                output_path = Path(runtime_outputs[-1].path)
                if output_path.is_file():
                    output_text = output_path.read_text()
            if "SDD_FACTORY_AGENT_BOOTSTRAP" in output_text:
                saw_bootstrap = True
            if routed_work_path.is_file() and saw_bootstrap:
                lowered = output_text.lower()
                if "pasted text #" in lowered or "paste again to expand" in lowered:
                    raise AssertionError(output_text[-4000:])
                if response.chunk_count > 0 or len(output_text) > 0:
                    break
            time.sleep(0.25)

        assert saw_bootstrap, "real launcher did not reach bootstrap"
        assert routed_work_path.is_file(), "routed work file was not materialized"

        routed_text = routed_work_path.read_text()
        assert f"Start implementation work for {task_key}." in routed_text
        lowered = output_text.lower()
        assert "pasted text #" not in lowered
        assert "paste again to expand" not in lowered

        print(f"Real launcher file handoff probe passed for session {session_id}.")


if __name__ == "__main__":
    main()
