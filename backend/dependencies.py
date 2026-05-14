"""Dependency wiring for API and coordinator services."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from backend.config import AppConfig, load_config
from backend.api.sse import SessionEventBus
from backend.coordinator.loop_runner import CoordinatorLoopRunner
from backend.coordinator.service import CoordinatorService
from backend.roles.contracts import DEFAULT_SESSION_ROLES
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.command_runner import CommandRunner
from backend.tools.gitlab_adapter import GitLabAdapter
from backend.tools.jira_adapter import JiraAdapter
from backend.tools.snapshot_adapter import SnapshotAdapter


@dataclass
class AppDependencies:
    """Shared application dependencies."""

    config: AppConfig
    database: Database
    session_repository: SessionRepository
    role_repository: RoleRepository
    event_repository: EventRepository
    artifact_repository: ArtifactRepository
    work_item_repository: WorkItemRepository
    session_backend: TmuxSessionBackend
    jira_adapter: JiraAdapter
    snapshot_adapter: SnapshotAdapter
    gitlab_adapter: GitLabAdapter
    event_bus: SessionEventBus
    loop_runner: CoordinatorLoopRunner
    coordinator_service: CoordinatorService


@lru_cache(maxsize=1)
def build_dependencies() -> AppDependencies:
    """Build the root dependency graph for the backend process."""

    config = load_config()
    database = Database(config.database_path)
    database.initialize()

    session_repository = SessionRepository(database)
    role_repository = RoleRepository(database)
    event_repository = EventRepository(database)
    artifact_repository = ArtifactRepository(database)
    work_item_repository = WorkItemRepository(database)
    session_backend = TmuxSessionBackend(
        mode=config.runtime_backend,
        runtime_root=config.runtime_root,
    )
    runner = CommandRunner()
    jira_adapter = JiraAdapter(runner, config.repo_root)
    snapshot_adapter = SnapshotAdapter(runner, config.repo_root)
    gitlab_adapter = GitLabAdapter(runner, config.repo_root)
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
        artifacts_root=config.workdir_root / "factory-artifacts",
        workdir_root=config.workdir_root,
        event_bus=event_bus,
    )
    loop_runner = CoordinatorLoopRunner(
        callback=coordinator_service.run_loop_once,
        interval_seconds=config.loop_interval_seconds,
    )
    return AppDependencies(
        config=config,
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
