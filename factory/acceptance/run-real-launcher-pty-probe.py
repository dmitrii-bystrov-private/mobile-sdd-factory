#!/usr/bin/env python3
"""Probe a real launcher-backed role under PTY hosting."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, prepare_session
from backend.api.schemas import CollectRoleOutputRequest, CreateSessionRequest, PrepareSessionRequest
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.dependencies import AppDependencies
from backend.roles.contracts import DEFAULT_SESSION_ROLES, IMPLEMENTER_ROLE
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.fake_adapters import FakeGitLabAdapter, FakeJiraAdapter, FakeSnapshotAdapter


def build_acceptance_dependencies(repo_root: Path, temp_root: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(
        mode="pty",
        runtime_root=temp_root / "workdir",
    )
    jira_adapter = FakeJiraAdapter(repo_root)
    snapshot_adapter = FakeSnapshotAdapter(repo_root, temp_root / "workdir")
    gitlab_adapter = FakeGitLabAdapter(repo_root)
    event_bus = SessionEventBus()
    coordinator_service = CoordinatorService(
        session_repository=session_repository,
        role_repository=role_repository,
        event_repository=event_repository,
        artifact_repository=artifact_repository,
        work_item_repository=work_item_repository,
        session_backend=session_backend,
        default_roles=DEFAULT_SESSION_ROLES,
        jira_adapter=jira_adapter,
        snapshot_adapter=snapshot_adapter,
        gitlab_adapter=gitlab_adapter,
        artifacts_root=temp_root / "workdir" / "factory-artifacts",
        workdir_root=temp_root / "workdir",
        event_bus=event_bus,
        role_workspace_manager=RoleWorkspaceManager(
            runtime_root=temp_root / "workdir",
            repo_root=repo_root,
            workdir_root=temp_root / "workdir",
        ),
        role_launcher_manager=RoleLauncherManager(
            repo_root=repo_root,
            workdir_root=temp_root / "workdir",
            launcher_command=["auto"],
        ),
    )
    loop_runner = CoordinatorLoopRunner(
        callback=coordinator_service.run_loop_once,
        interval_seconds=1.0,
    )
    return AppDependencies(
        config=None,  # type: ignore[arg-type]
        database=database,
        session_repository=session_repository,
        role_repository=role_repository,
        event_repository=event_repository,
        artifact_repository=artifact_repository,
        work_item_repository=work_item_repository,
        session_backend=session_backend,
        jira_adapter=jira_adapter,
        snapshot_adapter=snapshot_adapter,
        gitlab_adapter=gitlab_adapter,
        event_bus=event_bus,
        loop_runner=loop_runner,
        coordinator_service=coordinator_service,
    )


def collect_until_bootstrap(
    session_id: int,
    *,
    dependencies: AppDependencies,
    timeout_seconds: float = 12.0,
) -> tuple[object, str]:
    deadline = time.time() + timeout_seconds
    output_text = ""
    last_response = None
    while time.time() < deadline:
        response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=session_id,
                role_name=IMPLEMENTER_ROLE,
            ),
            dependencies=dependencies,
        )
        last_response = response
        artifacts = dependencies.artifact_repository.list_for_session(session_id)
        runtime_outputs = [item for item in artifacts if item.artifact_type == "runtime_output"]
        if runtime_outputs:
            output_path = Path(runtime_outputs[-1].path)
            if output_path.is_file():
                output_text = output_path.read_text()
        if "SDD_FACTORY_AGENT_BOOTSTRAP" in output_text:
            return response, output_text
        time.sleep(0.25)
    assert last_response is not None
    return last_response, output_text


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="sdd-factory-real-launcher-pty-probe.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = build_acceptance_dependencies(repo_root=repo_root, temp_root=temp_root)

        task_key = "IOS-ACCEPT-REAL-LAUNCHER-PTY-001"
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

        collect_response, output_text = collect_until_bootstrap(
            session_id=session_id,
            dependencies=deps,
        )
        assert collect_response.chunk_count > 0
        assert collect_response.session.current_stage == "implementation_requested"
        assert "SDD_FACTORY_ROLE_LAUNCHER_READY" in output_text
        assert "SDD_FACTORY_AGENT_BOOTSTRAP" in output_text
        assert len(output_text.strip()) > len("SDD_FACTORY_ROLE_LAUNCHER_READY\nSDD_FACTORY_AGENT_BOOTSTRAP")

        print(f"Real launcher PTY probe passed for session {session_id}.")


if __name__ == "__main__":
    main()
