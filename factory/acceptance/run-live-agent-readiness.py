#!/usr/bin/env python3
"""Probe live agent readiness and classify external blockers vs local runtime blockers."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess

from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import CreateSessionRequest, PrepareSessionRequest
from backend.roles.contracts import IMPLEMENTER_ROLE
from runtime_config import acceptance_role_config
from run_roots import managed_run_root


def load_story_acceptance_module():
    module_path = Path(__file__).resolve().parent / "run-story-subtasks-acceptance.py"
    spec = spec_from_file_location("story_subtasks_acceptance", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_probe(launch_script: Path, *, launcher_name: str) -> tuple[int, str]:
    proc = subprocess.Popen(
        [str(launch_script)],
        cwd=launch_script.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={
            **dict(subprocess.os.environ),
            "SDD_FACTORY_AGENT_EXECUTABLE": launcher_name,
        },
    )
    try:
        output, _ = proc.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
    return proc.returncode if proc.returncode is not None else -9, output or ""


def classify_probe(output: str) -> str:
    normalized = output.lower()
    if "operation not permitted, mkdir '/users/d.bystrov/.claude/projects/" in normalized:
        return "filesystem_blocker_claude"
    if "attempt to write a readonly database" in normalized:
        return "filesystem_blocker_codex"
    if "not logged in" in normalized or "please run /login" in normalized:
        return "auth_blocker"
    if "failed to connect to websocket" in normalized or "reconnecting..." in normalized:
        return "network_blocker"
    if "sdd_factory_agent_bootstrap" in normalized:
        return "launched"
    return "unknown"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    story_acceptance = load_story_acceptance_module()
    with managed_run_root(repo_root, "sdd-factory-live-agent-readiness") as temp_root:
        deps = story_acceptance.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-LIVE-READINESS-001"
        create_response = create_session(
            CreateSessionRequest(
                task_key=task_key,
                workflow_profile="oneshot",
                policy={
                    "self_review_policy": "disabled",
                    "boy_scout_policy": "disabled",
                    "doc_harvest_policy": "disabled",
                },
                role_config=acceptance_role_config(
                    ["implementer", "verification-coordinator"]
                ),
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

        claude_code, claude_output = run_probe(launch_script, launcher_name="claude")
        codex_code, codex_output = run_probe(launch_script, launcher_name="codex")

        claude_state = classify_probe(claude_output)
        codex_state = classify_probe(codex_output)

        assert claude_state != "filesystem_blocker_claude", claude_output
        assert codex_state != "filesystem_blocker_codex", codex_output
        assert claude_state in {"auth_blocker", "launched"}, claude_output
        assert codex_state in {"auth_blocker", "network_blocker", "launched"}, codex_output

        print("Live agent readiness probe passed.")
        print(f"claude_state={claude_state} returncode={claude_code}")
        print(f"codex_state={codex_state} returncode={codex_code}")


if __name__ == "__main__":
    main()
