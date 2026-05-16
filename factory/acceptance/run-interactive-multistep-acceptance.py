#!/usr/bin/env python3
"""Acceptance harness for multi-step interactive operator-assisted recovery."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from backend.api.routes_operator import send_runtime_input
from backend.api.routes_roles import collect_role_output
from backend.api.routes_sessions import create_session, get_interactive_state, prepare_session
from backend.api.schemas import (
    CollectRoleOutputRequest,
    CreateSessionRequest,
    PrepareSessionRequest,
    SendOperatorRuntimeInputRequest,
)
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


def build_dependencies(repo_root: Path, temp_root: Path, fixture: Path) -> AppDependencies:
    database = Database(temp_root / "acceptance.sqlite3")
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(mode="pty", runtime_root=temp_root / "workdir")
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
            launcher_command=["python3", "-u", str(fixture)],
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


def wait_for_status(
    session_id: int,
    *,
    dependencies: AppDependencies,
    expected_status: str | None = None,
    expected_stage: str | None = None,
    timeout_seconds: float = 6.0,
) -> object:
    deadline = time.time() + timeout_seconds
    last_response = None
    while time.time() < deadline:
        last_response = collect_role_output(
            CollectRoleOutputRequest(
                session_id=session_id,
                role_name=IMPLEMENTER_ROLE,
            ),
            dependencies=dependencies,
        )
        if (
            (expected_status is None or last_response.session.status == expected_status)
            and (expected_stage is None or last_response.session.current_stage == expected_stage)
        ):
            return last_response
        time.sleep(0.2)
    assert last_response is not None
    return last_response


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    fixture = repo_root / "tests" / "backend" / "fixtures" / "interactive_multistep_fixture.py"
    with tempfile.TemporaryDirectory(prefix="sdd-factory-interactive-multistep-acceptance.") as temp_dir:
        temp_root = Path(temp_dir)
        deps = build_dependencies(repo_root, temp_root, fixture)

        create_response = create_session(
            CreateSessionRequest(
                task_key="IOS-ACCEPT-INTERACTIVE-002",
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

        prepare_response = prepare_session(
            PrepareSessionRequest(task_key="IOS-ACCEPT-INTERACTIVE-002"),
            dependencies=deps,
        )
        assert prepare_response.followup_event_type == "implementation_requested"

        blocker_one = wait_for_status(
            session_id,
            dependencies=deps,
            expected_status="waiting_for_operator",
        )
        assert blocker_one.session.current_stage == "implementation_requested"
        interactive_one = get_interactive_state(session_id, dependencies=deps)
        assert interactive_one.available
        assert interactive_one.summary == "interactive auth required"

        send_runtime_input(
            SendOperatorRuntimeInputRequest(
                session_id=session_id,
                text="/mcp",
            ),
            dependencies=deps,
        )
        blocker_two = wait_for_status(
            session_id,
            dependencies=deps,
            expected_status="waiting_for_operator",
        )
        assert blocker_two.session.current_stage == "implementation_requested"
        interactive_two = get_interactive_state(session_id, dependencies=deps)
        assert interactive_two.available
        assert interactive_two.summary == "interactive confirmation required"

        send_runtime_input(
            SendOperatorRuntimeInputRequest(
                session_id=session_id,
                text="1",
            ),
            dependencies=deps,
        )
        completion = wait_for_status(
            session_id,
            dependencies=deps,
            expected_stage="verification_requested",
        )
        assert completion.session.status == "active"
        assert completion.session.current_owner == "verification-coordinator"

        interactive_after = get_interactive_state(session_id, dependencies=deps)
        assert not interactive_after.available

        print(f"Interactive multi-step acceptance passed for session {session_id}.")


if __name__ == "__main__":
    main()
