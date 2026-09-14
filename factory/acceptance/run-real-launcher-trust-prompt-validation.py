#!/usr/bin/env python3
"""Validate real launcher workspace trust behavior under tmux hosting."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import time

from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import CollectRoleOutputRequest, CreateSessionRequest, PrepareSessionRequest
from backend.roles.agent_trust import remove_task_role_workspace_trust
from backend.roles.contracts import IMPLEMENTER_ROLE, VERIFICATION_COORDINATOR_ROLE
from backend.session_backend.runtime_models import RuntimeRoleHandle
from runtime_config import acceptance_role_config
from run_roots import managed_run_root, shutdown_dependencies


def _load_probe_module(repo_root: Path):
    probe_path = repo_root / "factory" / "acceptance" / "run-real-launcher-tmux-probe.py"
    spec = importlib.util.spec_from_file_location("real_launcher_tmux_probe", probe_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load probe module from {probe_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_role_text(deps, session_id: int) -> str:
    collect_role_output(
        CollectRoleOutputRequest(
            session_id=session_id,
            role_name=IMPLEMENTER_ROLE,
        ),
        dependencies=deps,
    )
    artifacts = deps.artifact_repository.list_for_session(session_id)
    runtime_outputs = [item for item in artifacts if item.artifact_type == "runtime_output"]
    if not runtime_outputs:
        return ""
    output_path = Path(runtime_outputs[-1].path)
    return output_path.read_text() if output_path.is_file() else ""


def _wait_for_bootstrap(deps, session_id: int, *, timeout_seconds: float = 18.0) -> str:
    deadline = time.time() + timeout_seconds
    output_text = ""
    while time.time() < deadline:
        output_text = _collect_role_text(deps, session_id)
        if "SDD_FACTORY_AGENT_BOOTSTRAP" in output_text:
            return output_text
        time.sleep(0.25)
    return output_text


def _wait_for_trust_prompt_output(deps, session_id: int, *, timeout_seconds: float = 18.0) -> str:
    deadline = time.time() + timeout_seconds
    output_text = ""
    while time.time() < deadline:
        output_text = _collect_role_text(deps, session_id)
        if "Quick safety check" in output_text:
            return output_text
        time.sleep(0.25)
    return output_text


def _collect_for_duration(deps, session_id: int, *, duration_seconds: float) -> str:
    deadline = time.time() + duration_seconds
    output_text = ""
    while time.time() < deadline:
        output_text = _collect_role_text(deps, session_id)
        time.sleep(0.25)
    return output_text


def _wait_until_trust_prompt_cleared(deps, session_id: int, role_handle: str, *, timeout_seconds: float = 18.0) -> str:
    runtime_role = RuntimeRoleHandle(
        role_id=role_handle,
        session_id=role_handle.split(":", 1)[0],
        backend_name="tmux",
    )
    deadline = time.time() + timeout_seconds
    snapshot = ""
    while time.time() < deadline:
        _collect_role_text(deps, session_id)
        snapshot = deps.session_backend.capture_output_snapshot(runtime_role)
        if "Quick safety check" not in snapshot and deps.session_backend.launcher_role_ready(runtime_role):
            return snapshot
        time.sleep(0.25)
    return snapshot


def _create_prepared_session(deps, task_key: str, *, runner: str) -> tuple[int, str]:
    create_response = create_session(
        CreateSessionRequest(
            task_key=task_key,
            workflow_profile="oneshot",
            policy={
                "review_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
            role_config=acceptance_role_config(
                [IMPLEMENTER_ROLE, VERIFICATION_COORDINATOR_ROLE],
                runner_overrides={IMPLEMENTER_ROLE: runner, VERIFICATION_COORDINATOR_ROLE: "codex"},
            ),
        ),
        dependencies=deps,
    )
    session_id = create_response.session.id
    prepare_session(
        PrepareSessionRequest(task_key=task_key),
        dependencies=deps,
    )
    role = deps.role_repository.get_by_name(session_id, IMPLEMENTER_ROLE)
    assert role is not None
    assert role.runtime_handle is not None
    return session_id, role.runtime_handle


def _run_case(
    *,
    repo_root: Path,
    temp_root: Path,
    task_key: str,
    runner: str,
    pretrust_disabled: bool,
) -> tuple[str, str, str]:
    probe_module = _load_probe_module(repo_root)
    previous = os.environ.get("SDD_FACTORY_AGENT_PRETRUST_DISABLED")
    if pretrust_disabled:
        os.environ["SDD_FACTORY_AGENT_PRETRUST_DISABLED"] = "1"
    else:
        os.environ.pop("SDD_FACTORY_AGENT_PRETRUST_DISABLED", None)

    deps = None
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        deps = probe_module.build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)
        session_id, role_handle = _create_prepared_session(deps, task_key, runner=runner)
        output_text = _wait_for_bootstrap(deps, session_id)
        observed_output = (
            _collect_for_duration(deps, session_id, duration_seconds=4.0)
            if not pretrust_disabled
            else _wait_for_trust_prompt_output(deps, session_id)
        )
        snapshot = _wait_until_trust_prompt_cleared(deps, session_id, role_handle)
        return output_text, observed_output, snapshot
    finally:
        if deps is not None:
            shutdown_dependencies(deps)
        remove_task_role_workspace_trust(task_key, workdir_root=temp_root / "workdir")
        if previous is None:
            os.environ.pop("SDD_FACTORY_AGENT_PRETRUST_DISABLED", None)
        else:
            os.environ["SDD_FACTORY_AGENT_PRETRUST_DISABLED"] = previous


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runner = os.environ.get("SDD_FACTORY_TRUST_PROMPT_ACCEPTANCE_RUNNER", "claude").strip() or "claude"
    with managed_run_root(repo_root, "sdd-factory-real-launcher-trust-prompt") as temp_root:
        suffix = temp_root.name.split(".")[-1].upper()

        trusted_output, trusted_observed_output, trusted_snapshot = _run_case(
            repo_root=repo_root,
            temp_root=temp_root / "trusted",
            task_key=f"IOS-ACCEPT-TRUSTED-{suffix}",
            runner=runner,
            pretrust_disabled=False,
        )
        assert "SDD_FACTORY_AGENT_BOOTSTRAP" in trusted_output, trusted_output
        assert "Quick safety check" not in trusted_observed_output, trusted_observed_output
        assert "Quick safety check" not in trusted_snapshot, trusted_snapshot

        untrusted_output, untrusted_observed_output, untrusted_snapshot = _run_case(
            repo_root=repo_root,
            temp_root=temp_root / "untrusted",
            task_key=f"IOS-ACCEPT-UNTRUSTED-{suffix}",
            runner=runner,
            pretrust_disabled=True,
        )
        assert "SDD_FACTORY_AGENT_BOOTSTRAP" in untrusted_output, untrusted_output
        assert "Quick safety check" in untrusted_observed_output, untrusted_observed_output
        assert "Quick safety check" not in untrusted_snapshot, untrusted_snapshot

        print("Real launcher trust prompt validation passed.")
        print(f"runner={runner}")


if __name__ == "__main__":
    main()
