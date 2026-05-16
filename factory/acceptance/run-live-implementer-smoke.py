#!/usr/bin/env python3
"""Run a live launcher smoke against one persistent implementer role workspace."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import tempfile

from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import CreateSessionRequest, PrepareSessionRequest
from backend.roles.contracts import IMPLEMENTER_ROLE


def load_story_acceptance_module():
    module_path = Path(__file__).resolve().parent / "run-story-subtasks-acceptance.py"
    spec = spec_from_file_location("story_subtasks_acceptance", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    story_acceptance = load_story_acceptance_module()
    with tempfile.TemporaryDirectory(prefix="sdd-factory-live-implementer-smoke.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-LIVE-IMPL-001"
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
        prepare_session(
            PrepareSessionRequest(task_key=task_key),
            dependencies=deps,
        )

        implementer_role = deps.role_repository.get_by_name(create_response.session.id, IMPLEMENTER_ROLE)
        launch_command = deps.session_backend.get_spawn_command(implementer_role.runtime_handle)
        assert len(launch_command) == 1
        launch_script = Path(launch_command[0])
        assert launch_script.is_file(), launch_script

        proc = subprocess.Popen(
            [str(launch_script)],
            cwd=launch_script.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            output, _ = proc.communicate(timeout=5)
            output = output or ""
            assert "SDD_FACTORY_ROLE_LAUNCHER_READY" in output
            assert "SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude" in output
            assert "operation not permitted, mkdir '/Users/d.bystrov/.claude/projects/" not in output.lower()
            assert "attempt to write a readonly database" not in output.lower()
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()
            output = output or ""
            assert "SDD_FACTORY_ROLE_LAUNCHER_READY" in output
            assert "SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude" in output
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

        print("Live implementer runtime smoke passed.")


if __name__ == "__main__":
    main()
