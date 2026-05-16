from pathlib import Path
import tempfile
import time
import unittest

from backend.api.sse import SessionEventBus
from backend.coordinator.intake import IntakeError
from backend.coordinator.service import CoordinatorService
from backend.roles.contracts import (
    ALLOWED_STAGE_ROLE_TARGETS,
    BUG_FIXER_ROLE,
    CODE_REVIEWER_ROLE,
    DEFAULT_SESSION_ROLES,
    ACCEPTANCE_CRITERIA_WORKER_ROLE,
    CONSTRAINTS_WORKER_ROLE,
    PROPOSAL_CONTEXT_WORKER_ROLE,
    REQUIREMENTS_CLARIFIER_WORKER_ROLE,
    SPEC_VERIFIER_WORKER_ROLE,
    TASK_DECOMPOSER_WORKER_ROLE,
    STORY_SPEC_WORKER_ROLE,
)
from backend.roles.launcher import RoleLauncherManager
from backend.roles.workspace import RoleWorkspaceManager
from backend.session_backend.tmux_backend import TmuxSessionBackend
from backend.session_backend.runtime_models import RuntimeSessionHandle
from backend.state.artifact_repository import ArtifactRepository
from backend.state.db import Database
from backend.state.event_repository import EventRepository
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository
from backend.tools.command_runner import CommandResult


class FakeJiraAdapter:
    def resolve_parent(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["resolve_parent", task_key],
            returncode=0,
            stdout=f"{task_key}\n",
            stderr="",
        )

    def get_issue_type(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["get_issue_type", task_key],
            returncode=0,
            stdout="Story\n",
            stderr="",
        )

    def create_subtasks(self, task_key: str, plan_dir: Path) -> CommandResult:
        return CommandResult(
            command=["create_subtasks", task_key, str(plan_dir)],
            returncode=0,
            stdout="Created subtasks:\n01    IOS-90001     Build data source\n",
            stderr="",
        )

    def send_to_test(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["send_to_test", task_key],
            returncode=0,
            stdout=f"Done: {task_key} -> Ready for test\n",
            stderr="",
        )


class FakeSnapshotAdapter:
    def __init__(self, workdir_root: Path | None = None) -> None:
        self.workdir_root = workdir_root
        self.calls: list[str] = []
        self.statuses_by_task: dict[str, str] = {}

    def set_statuses_output(self, task_key: str, content: str) -> None:
        self.statuses_by_task[task_key] = content

    def run(self, task_key: str) -> CommandResult:
        self.calls.append(task_key)
        if self.workdir_root is not None and task_key in self.statuses_by_task:
            task_dir = self.workdir_root / task_key
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "statuses.md").write_text(self.statuses_by_task[task_key])
        return CommandResult(
            command=["snapshot", task_key],
            returncode=0,
            stdout="snapshot ok\n",
            stderr="",
        )


class FakeGitLabAdapter:
    def create_mr(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["create_mr", task_key],
            returncode=0,
            stdout=(
                f"Pushing branch for {task_key}\n"
                f"https://gitlab.example.com/mobile/{task_key}/-/merge_requests/42\n"
            ),
            stderr="",
        )

    def fetch_mr_comments(self, platform: str, mr_id: str) -> CommandResult:
        return CommandResult(
            command=["fetch_mr_comments", platform, mr_id],
            returncode=0,
            stdout=(
                f"# Unresolved MR discussions: !{mr_id} (2 total)\n\n"
                "## Discussion 1 — file_a.swift:10\n\n"
                "**Reviewer:** First comment\n\n"
                "---\n\n"
                "## Discussion 2 — file_b.swift:20\n\n"
                "**Reviewer:** Second comment\n\n"
                "---\n"
            ),
            stderr="",
        )


class SessionCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "factory.sqlite3"
        self.database = Database(self.db_path)
        self.database.initialize()

        self.session_repository = SessionRepository(self.database)
        self.role_repository = RoleRepository(self.database)
        self.event_repository = EventRepository(self.database)
        self.artifact_repository = ArtifactRepository(self.database)
        self.work_item_repository = WorkItemRepository(self.database)
        self.session_backend = TmuxSessionBackend(mode="recording")
        self.event_bus = SessionEventBus()
        self.snapshot_adapter = FakeSnapshotAdapter(Path(self.temp_dir.name))
        self.coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=self.session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=self.snapshot_adapter,
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=Path(self.temp_dir.name),
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
                launcher_command=["sh"],
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_statuses_file(self, task_key: str, content: str) -> None:
        task_dir = Path(self.temp_dir.name) / task_key
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "statuses.md").write_text(content)

    def test_create_task_session_creates_roles_and_event(self) -> None:
        session, event, created = self.coordinator.create_task_session(
            "IOS-30000",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )
        roles = self.role_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_started", event.event_type)
        self.assertEqual("active", session.status.value)
        self.assertEqual("bug_full", session.workflow_profile)
        self.assertEqual("required", session.policy["test_policy"])

    def test_collect_role_output_escalates_launcher_auth_blocker_to_operator(self) -> None:
        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "interactive_auth_blocker_fixture.py"
        )
        pty_backend = TmuxSessionBackend(
            mode="pty",
            runtime_root=Path(self.temp_dir.name),
        )
        self.coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=pty_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=self.snapshot_adapter,
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=Path(self.temp_dir.name),
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=Path(self.temp_dir.name) / "repo-root",
                workdir_root=Path(self.temp_dir.name),
                launcher_command=["python3", "-u", str(fixture)],
            ),
        )
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "disabled",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "disabled",
            },
        )
        self.coordinator.prepare_task_session("IOS-30001")

        updated_session = session
        chunk_count = 0
        for _ in range(20):
            updated_session, _, chunk_count = self.coordinator.collect_role_output(
                session_id=session.id,
                role_name="implementer",
            )
            if updated_session.status.value == "waiting_for_operator":
                break
            time.sleep(0.2)

        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertGreaterEqual(chunk_count, 2)
        work_items = self.work_item_repository.list_for_session(session.id)
        self.assertTrue(
            any(item.status.value == "waiting_for_operator" for item in work_items),
            "expected an assigned work item to be escalated to waiting_for_operator",
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.assertIsNotNone(implementer_role)
        runtime_session_id = implementer_role.runtime_handle.split(":", 1)[0]
        pty_backend.stop_session(RuntimeSessionHandle(session_id=runtime_session_id))

    def test_create_task_session_creates_role_workspaces(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000W",
            workflow_profile="oneshot",
            policy=None,
        )

        self.assertIsNotNone(session.id)
        for role_name in DEFAULT_SESSION_ROLES + [CODE_REVIEWER_ROLE]:
            role_dir = Path(self.temp_dir.name) / "IOS-30000W" / "runtime" / "role-workspaces" / role_name
            agents_path = role_dir / "AGENTS.md"
            claude_path = role_dir / "CLAUDE.md"
            self.assertTrue(role_dir.is_dir())
            self.assertTrue(agents_path.is_file())
            self.assertTrue(claude_path.is_symlink())
            self.assertEqual("AGENTS.md", claude_path.readlink().as_posix())
            agents_text = agents_path.read_text()
            self.assertIn(f"Role name: `{role_name}`", agents_text)
            self.assertIn("Task session: `IOS-30000W`", agents_text)

        implementer_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000W"
            / "runtime"
            / "role-workspaces"
            / "implementer"
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Task repo worktree:", implementer_agents)
        self.assertIn("Use RAG tools first for code exploration", implementer_agents)
        self.assertIn("Read all routed spec inputs before writing code.", implementer_agents)
        self.assertIn("Treat final test+lint verification as deferred to the coordinator.", implementer_agents)
        verification_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000W"
            / "runtime"
            / "role-workspaces"
            / "verification-coordinator"
            / "AGENTS.md"
        ).read_text()
        self.assertIn("run-test.sh", verification_agents)
        self.assertIn("Final verification report target:", verification_agents)
        self.assertIn("do not run `run-build.sh` here", verification_agents)
        self.assertIn("Do not modify product code.", verification_agents)
        reviewer_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000W"
            / "runtime"
            / "role-workspaces"
            / CODE_REVIEWER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Project conventions:", reviewer_agents)
        self.assertIn("Read previous review summaries first when they are provided", reviewer_agents)
        self.assertIn("Keep outputs compact and fixer-oriented.", reviewer_agents)

    def test_create_task_session_creates_bug_fixer_workspace_contract(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000BUGW",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )

        self.assertIsNotNone(session.id)
        bug_fixer_agents = (
            Path(self.temp_dir.name)
            / "IOS-30000BUGW"
            / "runtime"
            / "role-workspaces"
            / BUG_FIXER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Task description and comments:", bug_fixer_agents)
        self.assertIn("Bug analysis report target:", bug_fixer_agents)
        self.assertIn("Support the routed bug modes inside one runtime identity", bug_fixer_agents)
        self.assertIn("In `analysis-only` mode, read task description/comments first", bug_fixer_agents)
        self.assertIn("If an `Issues file:` path is routed, treat it as the primary narrow-scope input", bug_fixer_agents)
        self.assertIn("If `Follow-up comments:` are routed, prioritize the latest follow-up comments", bug_fixer_agents)

    def test_create_task_session_creates_role_launch_scripts(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30000L",
            workflow_profile="oneshot",
            policy=None,
        )

        self.assertIsNotNone(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        launch_script = (
            Path(self.temp_dir.name)
            / "IOS-30000L"
            / "runtime"
            / "role-workspaces"
            / "implementer"
            / "launch-role.sh"
        )
        self.assertTrue(launch_script.is_file())
        script_text = launch_script.read_text()
        self.assertIn("SDD_FACTORY_TASK_KEY=IOS-30000L", script_text)
        self.assertIn("SDD_FACTORY_ROLE_NAME=implementer", script_text)
        self.assertIn('exec sh', script_text)
        spawn_command = self.session_backend.get_spawn_command(implementer_role.runtime_handle)
        self.assertEqual([str(launch_script)], spawn_command)

    def test_default_role_launcher_uses_repo_bootstrap_script(self) -> None:
        workspace_manager = RoleWorkspaceManager(
            runtime_root=Path(self.temp_dir.name),
            repo_root=Path(self.temp_dir.name) / "repo-root-default-launcher",
            workdir_root=Path(self.temp_dir.name),
        )
        launcher_manager = RoleLauncherManager(
            repo_root=Path(self.temp_dir.name) / "repo-root-default-launcher",
            workdir_root=Path(self.temp_dir.name),
        )
        workspace = workspace_manager.ensure_role_workspace("IOS-30000AUTO", "implementer")
        launch_plan = launcher_manager.ensure_launch_plan(
            task_key="IOS-30000AUTO",
            workspace=workspace,
        )

        script_text = launch_plan.launcher_script.read_text()
        self.assertIn("SDD_FACTORY_WORKDIR_ROOT=", script_text)
        self.assertIn("SDD_FACTORY_TASK_REPO_ROOT=", script_text)
        self.assertIn("/factory/scripts/run-role-agent.sh", script_text)
        self.assertIn("SDD_FACTORY_ROLE_LAUNCHER_READY", script_text)

    def test_real_launcher_backed_runtime_keeps_persistent_role_context_across_rounds(self) -> None:
        runtime_root = Path(self.temp_dir.name)
        repo_root = Path(self.temp_dir.name) / "repo-root-real-launcher"
        session_backend = TmuxSessionBackend(mode="recording", runtime_root=runtime_root)
        coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts-real-launcher",
            workdir_root=Path(self.temp_dir.name),
            event_bus=self.event_bus,
            role_workspace_manager=RoleWorkspaceManager(
                runtime_root=runtime_root,
                repo_root=repo_root,
                workdir_root=Path(self.temp_dir.name),
            ),
            role_launcher_manager=RoleLauncherManager(
                repo_root=repo_root,
                workdir_root=Path(self.temp_dir.name),
            ),
        )

        session, _, _ = coordinator.create_task_session(
            "IOS-30000E2E",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = coordinator.prepare_task_session("IOS-30000E2E")

        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        verifier_role = self.role_repository.get_by_name(session.id, "verification-coordinator")

        for role in (implementer_role, reviewer_role, verifier_role):
            spawn_command = session_backend.get_spawn_command(role.runtime_handle)
            self.assertEqual(1, len(spawn_command))
            launch_script_text = Path(spawn_command[0]).read_text()
            self.assertIn("/factory/scripts/run-role-agent.sh", launch_script_text)

        coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean review"},
        )
        coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name="verification-coordinator",
            output_type="failed",
            payload={"summary": "verification failed", "failures": ["lint"]},
        )
        coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "verification correction done"},
        )

        implementer_inputs = session_backend.get_sent_inputs(implementer_role.runtime_handle)
        reviewer_inputs = session_backend.get_sent_inputs(reviewer_role.runtime_handle)
        verifier_inputs = session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertEqual(2, len(implementer_inputs))
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", implementer_inputs[0])
        self.assertIn(
            "Continue from your existing implementer role context in this persistent task session.",
            implementer_inputs[1],
        )

        self.assertEqual(1, len(reviewer_inputs))
        self.assertIn("Role-specific rules:", reviewer_inputs[0])
        self.assertIn("review_scope", reviewer_inputs[0])

        self.assertEqual(2, len(verifier_inputs))
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", verifier_inputs[0])
        self.assertIn(
            "Continue from your existing verification-coordinator role context in this persistent task session.",
            verifier_inputs[1],
        )

    def test_create_task_session_is_idempotent_for_existing_key(self) -> None:
        first_session, _, _ = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="oneshot",
            policy=None,
        )
        second_session, event, created = self.coordinator.create_task_session(
            "IOS-30001",
            workflow_profile="oneshot",
            policy=None,
        )
        roles = self.role_repository.list_for_session(first_session.id)

        self.assertFalse(created)
        self.assertEqual(first_session.id, second_session.id)
        self.assertEqual("task_session_reused", event.event_type)
        self.assertEqual(4, len(roles))

    def test_create_task_session_rejects_conflicting_existing_policy(self) -> None:
        self.coordinator.create_task_session(
            "IOS-30001A",
            workflow_profile="oneshot",
            policy=None,
        )

        with self.assertRaisesRegex(IntakeError, "different stored policy"):
            self.coordinator.create_task_session(
                "IOS-30001A",
                workflow_profile="oneshot",
                policy={"self_review_policy": "disabled"},
            )

    def test_prepare_task_session_runs_intake_and_registers_artifacts(self) -> None:
        session, event, created, details = self.coordinator.prepare_task_session("IOS-30002")
        artifacts = self.artifact_repository.list_for_session(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        refreshed_session = self.session_repository.get_by_task_key("IOS-30002")
        events = self.event_repository.list_for_session(session.id)

        self.assertTrue(created)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("IOS-30002", details["resolved_task_key"])
        self.assertEqual("Story", details["issue_type"])
        self.assertEqual(0, details["snapshot_exit_code"])
        self.assertEqual("implementation_requested", details["followup_event_type"])
        self.assertEqual(4, len(artifacts))
        self.assertEqual(1, len(work_items))
        self.assertEqual("Initial implementation for IOS-30002", work_items[0].title)
        self.assertEqual("implementation_requested", refreshed_session.current_stage)
        self.assertEqual("implementer", refreshed_session.current_owner)
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.assertEqual(1, implementer_role.last_hydration_version)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30002.", sent_inputs[0])
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("Use RAG tools first for code exploration", sent_inputs[0])
        self.assertIn("Final test+lint gate remains deferred to the coordinator.", sent_inputs[0])

    def test_prepare_task_session_reuses_existing_policy_aware_session(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002A",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "disabled",
                "doc_harvest_policy": "enabled",
            },
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002A")

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("oneshot", prepared_session.workflow_profile)
        self.assertEqual("required", prepared_session.policy["self_review_policy"])
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("implementation_requested", details["followup_event_type"])

    def test_prepare_task_session_routes_bug_full_into_bug_analysis(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002BUG")
        work_items = self.work_item_repository.list_for_session(prepared_session.id)
        events = self.event_repository.list_for_session(prepared_session.id)
        bug_fixer_role = self.role_repository.get_by_name(prepared_session.id, BUG_FIXER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("bug_analysis_requested", details["followup_event_type"])
        self.assertEqual("bug_analysis_requested", prepared_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, prepared_session.current_owner)
        self.assertEqual("bug_analysis", work_items[0].work_type)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "bug_analysis_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Mode: analysis-only", sent_inputs[0])
        self.assertIn("Analyze bug IOS-30002BUG before implementation.", sent_inputs[0])
        self.assertIn("Test policy for this session: required.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("In `analysis-only` mode, read task description/comments first", sent_inputs[0])
        self.assertIn('"bug_analysis_report_path"', sent_inputs[0])
        self.assertIn('"bug_mode": "analysis-only"', sent_inputs[0])
        self.assertIn('"primary_bug_inputs": "description.md + comments.md"', sent_inputs[0])

    def test_implementation_completed_moves_session_to_verification(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual(
            ["completed", "assigned"],
            [work_items[0].status.value, work_items[1].status.value],
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "role_input_dispatched",
                "verification_requested",
            ],
            [item.event_type for item in events],
        )
        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        self.assertEqual(1, verification_role.last_hydration_version)
        sent_inputs = self.session_backend.get_sent_inputs(verification_role.runtime_handle)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Run deterministic verification for IOS-30003.", sent_inputs[0])
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("Use `run-test.sh` and `run-lint.sh`; do not run `run-build.sh` here.", sent_inputs[0])
        self.assertIn("verification_report_path", sent_inputs[0])

    def test_implementation_completed_routes_to_reviewer_when_self_review_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003R",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003R")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        review_items = [
            item
            for item in self.work_item_repository.list_for_session(session.id)
            if item.work_type == "self_review"
        ]
        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)

        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual(CODE_REVIEWER_ROLE, updated_session.current_owner)
        self.assertEqual("self_review_requested", followup_event.event_type)
        self.assertEqual(1, len(review_items))
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Review the current task changes for IOS-30003R.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        self.assertIn("Start from the current diff and review only the touched changes.", sent_inputs[0])
        self.assertIn("review_scope", sent_inputs[0])

    def test_reviewer_output_passed_routes_self_review_to_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RP",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RP")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="passed",
            payload={"summary": "clean review"},
        )

        self.assertEqual("self_review_passed", mapped_event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)

    def test_reviewer_output_failed_routes_self_review_to_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003RF",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003RF")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="failed",
            payload={"summary": "issues remain"},
        )

        self.assertEqual("self_review_issues_found", mapped_event.event_type)
        self.assertEqual("self_review_correction_requested", followup_event.event_type)
        self.assertEqual("self_review_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)

    def test_second_self_review_dispatch_includes_previous_review_summary_paths(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003R2",
            workflow_profile="oneshot",
            policy={
                "self_review_policy": "required",
                "boy_scout_policy": "enabled",
                "doc_harvest_policy": "enabled",
            },
        )
        prepared_session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003R2")
        self.coordinator.handle_operator_event(
            session_id=prepared_session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        _, review_event, _ = self.coordinator.handle_role_output(
            session_id=prepared_session.id,
            role_name=CODE_REVIEWER_ROLE,
            output_type="failed",
            payload={"summary": "issues remain"},
        )

        refreshed = self.coordinator._get_session_or_raise(session.id)
        self.coordinator._enqueue_self_review(session=refreshed, source_event=review_event)

        reviewer_role = self.role_repository.get_by_name(session.id, CODE_REVIEWER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(reviewer_role.runtime_handle)
        self.assertEqual(2, len(sent_inputs))
        self.assertIn(
            "Previous review summaries (read first and do not re-flag the same issues):",
            sent_inputs[-1],
        )
        self.assertIn("previous_review_summary_paths", sent_inputs[-1])

    def test_bug_analysis_completed_moves_session_to_implementation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30003BUG")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="bug_analysis_completed",
            payload={
                "summary": "Likely missing state reset in coordinator",
                "test_strategy": "Add regression test for repeated resume path",
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        bug_fixer_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual(
            ["completed", "assigned"],
            [work_items[0].status.value, work_items[1].status.value],
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "bug_analysis_requested",
                "bug_analysis_completed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(2, len(bug_fixer_inputs))
        self.assertIn("Mode: fix-only", bug_fixer_inputs[-1])
        self.assertIn("Implement the bug fix for IOS-30003BUG", bug_fixer_inputs[-1])
        self.assertIn(
            "Bug analysis summary: Likely missing state reset in coordinator",
            bug_fixer_inputs[-1],
        )
        self.assertIn("Continue from your existing bug-fixer role context", bug_fixer_inputs[-1])
        self.assertIn('"bug_analysis_report_path"', bug_fixer_inputs[-1])
        self.assertIn('"bug_mode": "fix-only"', bug_fixer_inputs[-1])
        self.assertIn("In `fix-only` mode, read the saved `spec/bug-analysis.md` first", bug_fixer_inputs[-1])

    def test_prepare_task_session_routes_story_full_into_proposal_context(self) -> None:
        session, _, created = self.coordinator.create_task_session(
            "IOS-30002STORY",
            workflow_profile="story_full",
            policy=None,
        )

        prepared_session, event, prepared_created, details = self.coordinator.prepare_task_session("IOS-30002STORY")
        work_items = self.work_item_repository.list_for_session(prepared_session.id)
        events = self.event_repository.list_for_session(prepared_session.id)
        proposal_role = self.role_repository.get_by_name(prepared_session.id, PROPOSAL_CONTEXT_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(proposal_role.runtime_handle)

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("proposal_context_requested", details["followup_event_type"])
        self.assertEqual("proposal_context_requested", prepared_session.current_stage)
        self.assertEqual(PROPOSAL_CONTEXT_WORKER_ROLE, prepared_session.current_owner)
        self.assertEqual("proposal_context", work_items[0].work_type)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Collect compact proposal and context foundations for story IOS-30002STORY before final story spec.", sent_inputs[0])
        self.assertIn("Role-specific rules:", sent_inputs[0])
        launch_script = (
            Path(self.temp_dir.name)
            / "IOS-30002STORY"
            / "runtime"
            / "role-workspaces"
            / PROPOSAL_CONTEXT_WORKER_ROLE
            / "launch-role.sh"
        )
        self.assertTrue(launch_script.is_file())
        launch_script_text = launch_script.read_text()
        proposal_agents = (
            Path(self.temp_dir.name)
            / "IOS-30002STORY"
            / "runtime"
            / "role-workspaces"
            / PROPOSAL_CONTEXT_WORKER_ROLE
            / "AGENTS.md"
        ).read_text()
        self.assertIn("Proposal target:", proposal_agents)
        self.assertIn("Context directory:", proposal_agents)
        self.assertIn("bounded one-shot worker", proposal_agents)
        self.assertIn("SDD_FACTORY_ROLE_LIFECYCLE=one-shot", launch_script_text)
        self.assertIn("lifecycle=%s", launch_script_text)

    def test_proposal_context_completed_moves_story_session_to_requirements(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PC",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PC")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified", "context_findings": "Reuse existing presenter flow"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        requirements_role = self.role_repository.get_by_name(session.id, REQUIREMENTS_CLARIFIER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(requirements_role.runtime_handle)

        self.assertEqual("requirements_requested", updated_session.current_stage)
        self.assertEqual(REQUIREMENTS_CLARIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("requirements_requested", followup_event.event_type)
        self.assertEqual(
            [("proposal_context", "completed"), ("requirements", "assigned")],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Clarify the implementation requirements for story IOS-30003PC.", sent_inputs[0])
        self.assertIn("Proposal/context summary: Scope clarified", sent_inputs[0])
        self.assertIn("Key context findings: Reuse existing presenter flow", sent_inputs[0])

    def test_requirements_completed_moves_story_session_to_acceptance_criteria(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003REQ",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003REQ")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified", "assumptions": "Reuse existing screen state"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        acceptance_role = self.role_repository.get_by_name(session.id, ACCEPTANCE_CRITERIA_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(acceptance_role.runtime_handle)

        self.assertEqual("acceptance_criteria_requested", updated_session.current_stage)
        self.assertEqual(ACCEPTANCE_CRITERIA_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("acceptance_criteria_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "assigned"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare compact acceptance criteria for story IOS-30003REQ.", sent_inputs[0])
        self.assertIn("Requirements summary: Requirements clarified", sent_inputs[0])
        self.assertIn("Explicit assumptions: Reuse existing screen state", sent_inputs[0])

    def test_acceptance_criteria_completed_moves_story_session_to_constraints(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003ACC",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003ACC")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared", "highlighted_cases": "Retry + empty state"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        constraints_role = self.role_repository.get_by_name(session.id, CONSTRAINTS_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(constraints_role.runtime_handle)

        self.assertEqual("constraints_requested", updated_session.current_stage)
        self.assertEqual(CONSTRAINTS_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("constraints_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "assigned"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare compact implementation constraints for story IOS-30003ACC.", sent_inputs[0])
        self.assertIn("Acceptance criteria summary: Acceptance prepared", sent_inputs[0])
        self.assertIn("Highlighted cases: Retry + empty state", sent_inputs[0])

    def test_constraints_completed_moves_story_session_to_spec_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003CONSTR",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003CONSTR")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Respect analytics + assembly conventions", "key_constraints": "Reuse existing assembly pattern and analytics hooks"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        verifier_role = self.role_repository.get_by_name(session.id, SPEC_VERIFIER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(verifier_role.runtime_handle)

        self.assertEqual("spec_verification_requested", updated_session.current_stage)
        self.assertEqual(SPEC_VERIFIER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("spec_verification_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual("running", verifier_role.status.value)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Verify the assembled planning package for story IOS-30003CONSTR", sent_inputs[0])
        self.assertIn("Constraints summary: Respect analytics + assembly conventions", sent_inputs[0])
        self.assertIn("Key constraints: Reuse existing assembly pattern and analytics hooks", sent_inputs[0])

    def test_spec_verification_completed_moves_story_session_to_story_spec(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003VERIFY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003VERIFY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning package is coherent", "verified_focus": "navigation + state ownership"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        spec_role = self.role_repository.get_by_name(session.id, STORY_SPEC_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(spec_role.runtime_handle)

        self.assertEqual("story_spec_requested", updated_session.current_stage)
        self.assertEqual(STORY_SPEC_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("story_spec_requested", followup_event.event_type)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("story_spec", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare a concise implementation spec for story IOS-30003VERIFY before coding.", sent_inputs[0])
        self.assertIn("Planning verification summary: Planning package is coherent", sent_inputs[0])
        self.assertIn("Verified focus: navigation + state ownership", sent_inputs[0])

    def test_story_spec_completed_moves_session_to_task_decomposition(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003STORY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003STORY")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={
                "summary": "Need a new screen plus navigation wiring",
                "constraints": "Reuse existing assembly pattern and analytics hooks",
            },
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        decomposer_role = self.role_repository.get_by_name(session.id, TASK_DECOMPOSER_WORKER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(decomposer_role.runtime_handle)
        spec_role = self.role_repository.get_by_name(session.id, STORY_SPEC_WORKER_ROLE)

        self.assertEqual("task_decomposition_requested", updated_session.current_stage)
        self.assertEqual(TASK_DECOMPOSER_WORKER_ROLE, updated_session.current_owner)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual("stopped", spec_role.status.value)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("story_spec", "completed"),
                ("task_decomposition", "assigned"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_dispatched",
                "story_spec_requested",
                "story_spec_completed",
                "role_input_dispatched",
                "task_decomposition_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Prepare compact task decomposition for story IOS-30003STORY before implementation starts.", sent_inputs[0])
        self.assertIn("Story spec summary: Need a new screen plus navigation wiring", sent_inputs[0])

    def test_task_decomposition_completed_moves_session_to_implementation(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003DECOMP",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003DECOMP")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need a new screen plus navigation wiring"},
        )
        self.write_statuses_file(
            "IOS-30003DECOMP",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003DECOMP | Story | Parent story | In Progress |
| IOS-30030 | Sub-task | Already done one | Ready for test |
| IOS-30031 | Sub-task | Already done two | Released |
""",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={"summary": "Split into execution chunks", "task_breakdown": "Networking, state, UI wiring"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        implementer_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        decomposer_role = self.role_repository.get_by_name(session.id, TASK_DECOMPOSER_WORKER_ROLE)

        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("stopped", decomposer_role.status.value)
        self.assertEqual(
            [
                ("acceptance_criteria", "completed"),
                ("constraints", "completed"),
                ("implementation", "assigned"),
                ("proposal_context", "completed"),
                ("requirements", "completed"),
                ("spec_verification", "completed"),
                ("story_spec", "completed"),
                ("task_decomposition", "completed"),
            ],
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_dispatched",
                "story_spec_requested",
                "story_spec_completed",
                "role_input_dispatched",
                "task_decomposition_requested",
                "task_decomposition_completed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )
        self.assertEqual(1, len(implementer_inputs))
        self.assertIn("Start implementation work for IOS-30003DECOMP.", implementer_inputs[0])
        self.assertIn("Task decomposition summary: Split into execution chunks", implementer_inputs[0])

    def test_task_decomposition_completed_writes_legacy_plan_package_when_provided(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003PLAN",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003PLAN")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Scope clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.write_statuses_file(
            "IOS-30003PLAN",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003PLAN | Story | Parent story | In Progress |
| IOS-30032 | Sub-task | Existing subtask | Ready for test |
""",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Decomposition prepared",
                "plan_index_markdown": "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n",
                "plan_task_files": [
                    {
                        "filename": "01-build-data-source.md",
                        "content": "# Build data source\n\n## What to implement\nCreate the feature data source.\n",
                    }
                ],
            },
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        plan_dir = Path(self.temp_dir.name) / "IOS-30003PLAN" / "plan"

        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertTrue((plan_dir / "index.md").is_file())
        self.assertTrue((plan_dir / "01-build-data-source.md").is_file())
        self.assertTrue(
            any(artifact.artifact_type == "task_decomposition_plan_index" for artifact in artifacts)
        )
        self.assertTrue(
            any(artifact.artifact_type == "task_decomposition_plan_package" for artifact in artifacts)
        )

    def test_create_subtasks_from_plan_records_batch_artifacts(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBBATCH",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SUBBATCH")
        plan_dir = Path(self.temp_dir.name) / "IOS-30003SUBBATCH" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "index.md").write_text(
            "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n"
        )
        (plan_dir / "01-build-data-source.md").write_text(
            "# Build data source\n\n## What to implement\nCreate the feature data source.\n"
        )

        updated_session, event, followup_event = self.coordinator.create_subtasks_from_plan(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("jira_subtasks_created", event.event_type)
        self.assertEqual(["IOS-90001"], event.payload["created_subtask_keys"])
        self.assertIsNone(followup_event)
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_stderr" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "jira_subtasks_summary" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "subtasks_snapshot_stderr" for item in artifacts))
        self.assertEqual(0, event.payload["snapshot_refresh_exit_code"])

    def test_create_subtasks_from_plan_can_auto_start_subtask_lane(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBAUTO",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30003SUBAUTO")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Need explicit decomposition package"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={
                "summary": "Decomposition prepared",
                "plan_index_markdown": "# Execution Task List\n\n| # | Task | Depends on | Status |\n|---|------|------------|--------|\n| 01 | [Build data source](./01-build-data-source.md) | — | ☐ |\n",
                "plan_task_files": [
                    {
                        "filename": "01-build-data-source.md",
                        "content": "# Build data source\n\n## What to implement\nCreate the feature data source.\n",
                    }
                ],
            },
        )
        self.write_statuses_file(
            "IOS-30003SUBAUTO",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBAUTO | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Build data source | To Do |
| IOS-30041 | Sub-task | Finish docs | Ready for test |
""",
        )

        updated_session, event, followup_event = self.coordinator.create_subtasks_from_plan(session.id)

        self.assertEqual("jira_subtasks_created", event.event_type)
        self.assertIsNotNone(followup_event)
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)

    def test_knowledge_is_repo_visible_markdown(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30003KNOW")
        _, event = self.coordinator.create_knowledge(
            session_id=session.id,
            title="Reuse existing formatter helper",
            guidance="Do not add a new helper here; reuse the shared formatter already used in this module.",
            scope="shared-formatting",
        )

        knowledge_files = list(
            (Path(self.temp_dir.name) / "IOS-30003KNOW" / "repo" / "knowledge").rglob("*.md")
        )
        self.assertEqual("knowledge_created", event.event_type)
        self.assertTrue(any("Reuse existing formatter helper" in path.read_text() for path in knowledge_files))
        self.assertTrue(any("shared-formatting" in str(path) for path in knowledge_files))

    def test_start_subtask_graph_converts_story_implementation_into_subtask_lane(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30003SUBTASK",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30003SUBTASK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.write_statuses_file(
            "IOS-30003SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBTASK | Story | Parent story | In Progress |
| IOS-30013 | Sub-task | Already done one | Ready for test |
| IOS-30014 | Sub-task | Already done two | Released |
""",
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={"summary": "Execution chunks prepared"},
        )
        self.write_statuses_file(
            "IOS-30003SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30003SUBTASK | Story | Parent story | In Progress |
| IOS-30010 | Sub-task | Implement networking layer | To Do |
| IOS-30011 | Sub-task | Wire screen presentation | In Progress |
| IOS-30012 | Sub-task | Update docs | Ready for test |
""",
        )

        updated_session, event, followup_event = self.coordinator.start_subtask_graph(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("subtask_graph_requested", event.event_type)
        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual(
            sorted(
                [
                    ("acceptance_criteria", "completed"),
                    ("constraints", "completed"),
                    ("proposal_context", "completed"),
                    ("requirements", "completed"),
                    ("spec_verification", "completed"),
                    ("story_spec", "completed"),
                    ("task_decomposition", "completed"),
                    ("subtask_implementation", "assigned"),
                    ("subtask_implementation", "unassigned"),
                ]
            ),
            sorted((item.work_type, item.status.value) for item in work_items),
        )
        self.assertIn("Implement subtask IOS-30010", sent_inputs[-1])
        self.assertIn("Use the latest task decomposition artifact as the primary execution plan input.", sent_inputs[-1])
        self.assertIn("decomposition_artifact_path", sent_inputs[-1])

    def test_subtask_completion_assigns_next_subtask_before_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTASK",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBTASK")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.write_statuses_file(
            "IOS-30004SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTASK | Story | Parent story | In Progress |
| IOS-30022 | Sub-task | Already done one | Ready for test |
| IOS-30023 | Sub-task | Already done two | Released |
""",
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={"summary": "Execution chunks prepared"},
        )
        self.write_statuses_file(
            "IOS-30004SUBTASK",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTASK | Story | Parent story | In Progress |
| IOS-30020 | Sub-task | Add data source | To Do |
| IOS-30021 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "First subtask implemented"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertEqual(
            ["assigned", "completed", "completed", "completed", "completed", "completed", "completed", "completed", "completed"],
            sorted(item.status.value for item in work_items),
        )

        final_session, final_followup = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "Second subtask implemented"},
        )

        self.assertEqual("verification_requested", final_followup.event_type)
        self.assertEqual("verification_requested", final_session.current_stage)

    def test_subtask_completion_refreshes_snapshot_and_rewrites_graph(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBREFRESH",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBREFRESH")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={"summary": "Execution chunks prepared"},
        )
        self.write_statuses_file(
            "IOS-30004SUBREFRESH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBREFRESH | Story | Parent story | In Progress |
| IOS-30030 | Sub-task | Add data source | To Do |
| IOS-30031 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)
        self.snapshot_adapter.set_statuses_output(
            "IOS-30004SUBREFRESH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBREFRESH | Story | Parent story | In Progress |
| IOS-30030 | Sub-task | Add data source | Ready for test |
| IOS-30031 | Sub-task | Wire view state | To Do |
""",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "First subtask implemented"},
        )

        artifacts = self.artifact_repository.list_for_session(session.id)
        subtask_graph_artifacts = [
            artifact for artifact in artifacts if artifact.artifact_type == "subtask_statuses_markdown"
        ]
        refresh_stdout_artifacts = [
            artifact for artifact in artifacts if artifact.artifact_type == "subtask_snapshot_refresh_stdout"
        ]
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("subtask_implementation_requested", followup_event.event_type)
        self.assertEqual("subtask_implementation_requested", updated_session.current_stage)
        self.assertGreaterEqual(
            self.snapshot_adapter.calls.count("IOS-30004SUBREFRESH"),
            2,
        )
        self.assertGreaterEqual(len(subtask_graph_artifacts), 2)
        self.assertEqual(1, len(refresh_stdout_artifacts))
        self.assertTrue(
            any(event.event_type == "subtask_snapshot_refreshed" for event in events)
        )

    def test_subtask_completion_uses_refreshed_snapshot_as_remaining_source_of_truth(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004SUBTRUTH",
            workflow_profile="story_full",
            policy={"self_review_policy": "disabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004SUBTRUTH")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="proposal_context_completed",
            payload={"summary": "Context prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="requirements_completed",
            payload={"summary": "Requirements clarified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="acceptance_criteria_completed",
            payload={"summary": "Acceptance prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="constraints_completed",
            payload={"summary": "Constraints prepared"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="spec_verification_completed",
            payload={"summary": "Planning verified"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="story_spec_completed",
            payload={"summary": "Split into focused subtasks"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="task_decomposition_completed",
            payload={"summary": "Execution chunks prepared"},
        )
        self.write_statuses_file(
            "IOS-30004SUBTRUTH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTRUTH | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Add data source | To Do |
| IOS-30041 | Sub-task | Wire view state | To Do |
""",
        )
        self.coordinator.start_subtask_graph(session.id)
        self.snapshot_adapter.set_statuses_output(
            "IOS-30004SUBTRUTH",
            """# Statuses

| Key | Type | Title | Status |
| --- | --- | --- | --- |
| IOS-30004SUBTRUTH | Story | Parent story | In Progress |
| IOS-30040 | Sub-task | Add data source | Ready for test |
| IOS-30041 | Sub-task | Wire view state | Released |
""",
        )

        final_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="subtask_completed",
            payload={"summary": "First subtask implemented"},
        )

        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", final_session.current_stage)
        self.assertEqual(
            0,
            len(
                [
                    item
                    for item in work_items
                    if item.work_type == "subtask_implementation"
                    and item.status.value == "unassigned"
                ]
            ),
        )

    def test_verification_failed_moves_session_back_to_implementer(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"failures": ["test", "lint"]},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertEqual(
            sorted(
                [
                    ("Verification corrections for IOS-30004", "assigned"),
                    ("Initial implementation for IOS-30004", "completed"),
                    ("Verification for IOS-30004", "completed"),
                ]
            ),
            sorted((item.title, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "role_input_dispatched",
                "verification_requested",
                "verification_failed",
                "role_input_dispatched",
                "verification_correction_requested",
            ],
            [item.event_type for item in events],
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.assertEqual(2, implementer_role.last_hydration_version)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Apply verification corrections for IOS-30004.", sent_inputs[-1])
        self.assertIn("Continue from your existing implementer role context", sent_inputs[-1])
        self.assertIn("If the routed work is a narrow correction pass", sent_inputs[-1])
        self.assertNotIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[-1])

    def test_bug_full_verification_failed_routes_back_to_bug_fixer_with_fix_only_mode(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30004BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30004BUG")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="bug_analysis_completed",
            payload={"summary": "root cause found"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "bug fix done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"failures": ["test"]},
        )
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertEqual("verification_correction_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual("verification_correction_requested", followup_event.event_type)
        self.assertIn("Mode: fix-only", sent_inputs[-1])
        self.assertIn("Apply verification corrections for IOS-30004BUG.", sent_inputs[-1])
        self.assertIn("narrow bug-fix correction pass", sent_inputs[-1])
        self.assertIn('"issues_file_path"', sent_inputs[-1])
        self.assertIn('"bug_analysis_report_path"', sent_inputs[-1])

    def test_second_verification_dispatch_uses_continuation_prompt(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30004V2")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_failed",
            payload={"failures": ["test"]},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "corrections done"},
        )

        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        sent_inputs = self.session_backend.get_sent_inputs(verification_role.runtime_handle)

        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[0])
        self.assertIn(
            "Continue from your existing verification-coordinator role context",
            sent_inputs[-1],
        )
        self.assertNotIn("Read AGENTS.md/CLAUDE.md in the current directory now.", sent_inputs[-1])

    def test_verification_passed_completes_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30005")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "implementation done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all checks passed"},
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.current_stage)
        self.assertIsNone(updated_session.current_owner)
        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("task_completed", followup_event.event_type)
        self.assertEqual(
            sorted(
                [
                    ("Initial implementation for IOS-30005", "completed"),
                    ("Verification for IOS-30005", "completed"),
                ]
            ),
            sorted((item.title, item.status.value) for item in work_items),
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "role_input_dispatched",
                "verification_requested",
                "verification_passed",
                "task_completed",
            ],
            [item.event_type for item in events],
        )

    def test_role_output_completed_moves_implementer_flow_forward(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30006")

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="implementer",
            output_type="completed",
            payload={"summary": "done"},
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("implementation_completed", mapped_event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertTrue(
            any(artifact.artifact_type == "role_output_json" for artifact in artifacts)
        )
        self.assertEqual(
            [
                "task_started",
                "task_prepared",
                "role_input_dispatched",
                "implementation_requested",
                "implementation_completed",
                "role_input_dispatched",
                "verification_requested",
            ],
            [item.event_type for item in events],
        )

    def test_role_output_completed_moves_bug_analysis_forward(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30006BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30006BUG")

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=BUG_FIXER_ROLE,
            output_type="completed",
            payload={"summary": "Root cause isolated"},
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("bug_analysis_completed", mapped_event.event_type)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "bug_analysis_requested",
                "bug_analysis_completed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )

    def test_role_output_completed_moves_story_spec_forward(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30006STORY",
            workflow_profile="story_full",
            policy=None,
        )
        self.coordinator.prepare_task_session("IOS-30006STORY")
        proposal_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=PROPOSAL_CONTEXT_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Context prepared"},
        )

        self.assertEqual("proposal_context_completed", mapped_event.event_type)
        self.assertEqual("requirements_requested", followup_event.event_type)
        self.assertEqual("requirements_requested", proposal_session.current_stage)

        requirements_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=REQUIREMENTS_CLARIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Requirements prepared"},
        )

        self.assertEqual("requirements_completed", mapped_event.event_type)
        self.assertEqual("acceptance_criteria_requested", followup_event.event_type)
        self.assertEqual("acceptance_criteria_requested", requirements_session.current_stage)

        acceptance_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=ACCEPTANCE_CRITERIA_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Acceptance prepared"},
        )

        self.assertEqual("acceptance_criteria_completed", mapped_event.event_type)
        self.assertEqual("constraints_requested", followup_event.event_type)
        self.assertEqual("constraints_requested", acceptance_session.current_stage)

        constraints_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=CONSTRAINTS_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Constraints prepared"},
        )

        self.assertEqual("constraints_completed", mapped_event.event_type)
        self.assertEqual("spec_verification_requested", followup_event.event_type)
        self.assertEqual("spec_verification_requested", constraints_session.current_stage)

        verifier_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=SPEC_VERIFIER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Planning verified"},
        )

        self.assertEqual("spec_verification_completed", mapped_event.event_type)
        self.assertEqual("story_spec_requested", followup_event.event_type)
        self.assertEqual("story_spec_requested", verifier_session.current_stage)

        decomposition_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=STORY_SPEC_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Scope clarified"},
        )

        self.assertEqual("story_spec_completed", mapped_event.event_type)
        self.assertEqual("task_decomposition_requested", followup_event.event_type)
        self.assertEqual("task_decomposition_requested", decomposition_session.current_stage)

        updated_session, mapped_event, followup_event = self.coordinator.handle_role_output(
            session_id=session.id,
            role_name=TASK_DECOMPOSER_WORKER_ROLE,
            output_type="completed",
            payload={"summary": "Decomposition prepared"},
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("task_decomposition_completed", mapped_event.event_type)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual(
            [
                "task_started",
                "task_session_reused",
                "task_prepared",
                "role_input_dispatched",
                "proposal_context_requested",
                "proposal_context_completed",
                "role_input_dispatched",
                "requirements_requested",
                "requirements_completed",
                "role_input_dispatched",
                "acceptance_criteria_requested",
                "acceptance_criteria_completed",
                "role_input_dispatched",
                "constraints_requested",
                "constraints_completed",
                "role_input_dispatched",
                "spec_verification_requested",
                "spec_verification_completed",
                "role_input_dispatched",
                "story_spec_requested",
                "story_spec_completed",
                "role_input_dispatched",
                "task_decomposition_requested",
                "task_decomposition_completed",
                "role_input_dispatched",
                "implementation_requested",
            ],
            [item.event_type for item in events],
        )

    def test_collect_role_output_records_runtime_output_artifact(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30007")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(implementer_role.runtime_handle, "runtime line 1")
        self.session_backend.simulate_output(implementer_role.runtime_handle, "runtime line 2")

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual(2, chunk_count)
        self.assertTrue(any(artifact.artifact_type == "runtime_output" for artifact in artifacts))

    def test_poll_session_output_collects_chunks_for_multiple_roles(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30008")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        verification_role = self.role_repository.get_by_name(session.id, "verification-coordinator")
        self.session_backend.simulate_output(implementer_role.runtime_handle, "impl output")
        self.session_backend.simulate_output(verification_role.runtime_handle, "verify output")

        updated_session, event, role_count, chunk_count = self.coordinator.poll_session_output(
            session_id=session.id,
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(session.id, updated_session.id)
        self.assertEqual("session_output_polled", event.event_type)
        self.assertEqual(4, role_count)
        self.assertEqual(2, chunk_count)
        self.assertEqual(
            2,
            len([artifact for artifact in artifacts if artifact.artifact_type == "runtime_output"]),
        )

    def test_collect_role_output_normalizes_structured_marker(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30009")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_OUTPUT: {"output_type":"completed","payload":{"summary":"done"}}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.event_type == "verification_requested" for item in events))

    def test_collect_role_output_records_progress_marker_without_stage_transition(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30010")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_PROGRESS: {"status":"in_progress","message":"halfway there","progress":50}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertTrue(any(item.event_type == "role_progress_reported" for item in events))
        self.assertFalse(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.artifact_type == "runtime_progress_json" for item in artifacts))

    def test_collect_role_output_records_error_marker_without_stage_transition(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30014")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )

        updated_session, event, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        events = self.event_repository.list_for_session(session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual(1, chunk_count)
        self.assertEqual("role_output_collected", event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertIsNone(updated_session.current_owner)
        work_items = self.work_item_repository.list_for_session(session.id)
        self.assertEqual("waiting_for_operator", work_items[0].status.value)
        self.assertTrue(any(item.event_type == "role_runtime_error_reported" for item in events))
        self.assertTrue(any(item.event_type == "session_escalated_to_operator" for item in events))
        self.assertFalse(any(item.event_type == "implementation_completed" for item in events))
        self.assertTrue(any(item.artifact_type == "runtime_error_json" for item in artifacts))

    def test_event_bus_receives_published_session_events(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30015")
        self.coordinator.handle_role_output(
            session_id=session.id,
            role_name="implementer",
            output_type="completed",
            payload={"summary": "done"},
        )

        recent = self.event_bus.recent_events(session_id=session.id)

        self.assertTrue(any(event.event_type == "implementation_completed" for event in recent))
        self.assertTrue(any(event.event_type == "verification_requested" for event in recent))

    def test_run_loop_once_polls_all_active_sessions(self) -> None:
        session_a, _, _, _ = self.coordinator.prepare_task_session("IOS-30011")
        session_b, _, _, _ = self.coordinator.prepare_task_session("IOS-30012")
        implementer_a = self.role_repository.get_by_name(session_a.id, "implementer")
        implementer_b = self.role_repository.get_by_name(session_b.id, "implementer")
        self.session_backend.simulate_output(implementer_a.runtime_handle, "a output")
        self.session_backend.simulate_output(implementer_b.runtime_handle, "b output")

        event, session_count, chunk_count = self.coordinator.run_loop_once()
        artifacts_a = self.artifact_repository.list_for_session(session_a.id)
        artifacts_b = self.artifact_repository.list_for_session(session_b.id)

        self.assertEqual("coordinator_loop_ran", event.event_type)
        self.assertEqual(2, session_count)
        self.assertEqual(2, chunk_count)
        self.assertTrue(any(artifact.artifact_type == "runtime_output" for artifact in artifacts_a))
        self.assertTrue(any(artifact.artifact_type == "runtime_output" for artifact in artifacts_b))

    def test_run_loop_once_reconciles_undispatched_work_item(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30013",
            workflow_profile="oneshot",
            policy=None,
        )
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        work_item = self.work_item_repository.create(
            session_id=session.id,
            work_type="implementation",
            title="Recovered implementation for IOS-30013",
            owner_role_id=implementer_role.id,
            priority=100,
        )
        self.session_repository.update_stage_and_owner(
            session.id,
            current_stage="implementation_requested",
            current_owner="implementer",
        )

        event, session_count, chunk_count = self.coordinator.run_loop_once()
        events = self.event_repository.list_for_session(session.id)
        refreshed_role = self.role_repository.get_by_name(session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("coordinator_loop_ran", event.event_type)
        self.assertEqual(1, session_count)
        self.assertEqual(0, chunk_count)
        self.assertEqual(1, refreshed_role.last_hydration_version)
        self.assertEqual(1, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30013.", sent_inputs[0])
        self.assertTrue(
            any(
                item.event_type == "role_input_dispatched"
                and item.payload.get("work_item_id") == work_item.id
                for item in events
            )
        )
        self.assertTrue(any(item.event_type == "session_dispatch_reconciled" for item in events))

    def test_run_loop_once_skips_session_escalated_to_operator(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30016")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )

        updated_session, _, chunk_count = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        self.assertEqual("waiting_for_operator", updated_session.status.value)
        self.assertEqual(1, chunk_count)

        self.session_backend.simulate_output(implementer_role.runtime_handle, "should stay unread")
        event, session_count, loop_chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(0, session_count)
        self.assertEqual(0, loop_chunk_count)

    def test_pause_session_moves_active_session_to_paused(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30017")

        paused_session, event = self.coordinator.pause_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("paused", paused_session.status.value)
        self.assertEqual("implementer", paused_session.current_owner)
        self.assertEqual("session_paused_by_operator", event.event_type)
        self.assertTrue(any(item.event_type == "session_paused_by_operator" for item in events))

    def test_run_loop_once_skips_paused_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30018")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.coordinator.pause_session(session.id)
        self.session_backend.simulate_output(implementer_role.runtime_handle, "should stay unread")

        event, session_count, chunk_count = self.coordinator.run_loop_once()

        self.assertIsNone(event)
        self.assertEqual(0, session_count)
        self.assertEqual(0, chunk_count)

    def test_ingest_mr_comments_reopens_completed_session_with_followup_work(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30020")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event, followup_event, discussion_count = self.coordinator.ingest_mr_comments(
            session_id=completed_session.id,
            platform="ios",
            mr_id="2942",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("mr_followup_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("mr_comments_received", event.event_type)
        self.assertEqual("mr_followup_requested", followup_event.event_type)
        self.assertEqual(2, discussion_count)
        self.assertTrue(
            any(item.title == "MR follow-up for IOS-30020 from !2942" for item in work_items)
        )
        self.assertTrue(
            any(item.work_type == "followup_implementation" for item in work_items)
        )
        self.assertTrue(any(item.event_type == "mr_comments_received" for item in events))
        self.assertTrue(any(item.event_type == "mr_followup_requested" for item in events))

    def test_reopen_from_qa_reactivates_completed_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event, followup_event = self.coordinator.reopen_from_qa(
            session_id=completed_session.id,
            comment_text="QA: still broken on edge case",
        )
        work_items = self.work_item_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("qa_reopen_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertEqual("qa_reopened", event.event_type)
        self.assertEqual("qa_reopen_requested", followup_event.event_type)
        self.assertTrue(
            any(item.title == "QA reopen follow-up for IOS-30021" for item in work_items)
        )
        self.assertTrue(
            any(item.work_type == "followup_implementation" for item in work_items)
        )
        self.assertTrue(any(item.event_type == "qa_reopened" for item in events))
        self.assertTrue(any(item.event_type == "qa_reopen_requested" for item in events))

    def test_bug_full_qa_reopen_uses_bug_fixer_fix_only_followup(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021BUG",
            workflow_profile="bug_full",
            policy={"test_policy": "enabled"},
        )
        self.coordinator.prepare_task_session("IOS-30021BUG")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="bug_analysis_completed",
            payload={"summary": "root cause found"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event, followup_event = self.coordinator.reopen_from_qa(
            session_id=session.id,
            comment_text="QA: still broken on edge case",
        )
        bug_fixer_role = self.role_repository.get_by_name(session.id, BUG_FIXER_ROLE)
        sent_inputs = self.session_backend.get_sent_inputs(bug_fixer_role.runtime_handle)

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("qa_reopen_requested", updated_session.current_stage)
        self.assertEqual(BUG_FIXER_ROLE, updated_session.current_owner)
        self.assertEqual("qa_reopened", event.event_type)
        self.assertEqual("qa_reopen_requested", followup_event.event_type)
        self.assertIn("Mode: fix-only", sent_inputs[-1])
        self.assertIn("Apply QA reopen follow-up changes for IOS-30021BUG.", sent_inputs[-1])
        self.assertIn("highest-priority follow-up scope", sent_inputs[-1])
        self.assertIn('"followup_comments_path"', sent_inputs[-1])
        self.assertIn('"bug_analysis_report_path"', sent_inputs[-1])

    def test_create_mr_handoff_marks_completed_session_as_handed_off(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021A")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event, mr_url = self.coordinator.create_mr_handoff(
            session_id=completed_session.id
        )
        artifacts = self.artifact_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("mr_handoff_completed", updated_session.current_stage)
        self.assertEqual("mr_handoff_completed", event.event_type)
        self.assertEqual(
            "https://gitlab.example.com/mobile/IOS-30021A/-/merge_requests/42",
            mr_url,
        )
        self.assertTrue(any(item.artifact_type == "mr_handoff_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "mr_handoff_stderr" for item in artifacts))
        self.assertTrue(any(item.event_type == "mr_handoff_completed" for item in events))

    def test_create_mr_handoff_requires_completed_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021B")

        with self.assertRaisesRegex(IntakeError, "must be completed before MR handoff"):
            self.coordinator.create_mr_handoff(session_id=session.id)

    def test_send_to_test_handoff_marks_mr_handed_off_session_as_ready(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021C")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.create_mr_handoff(session_id=completed_session.id)

        updated_session, event = self.coordinator.send_to_test_handoff(session_id=session.id)
        artifacts = self.artifact_repository.list_for_session(session.id)
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("send_to_test_completed", updated_session.current_stage)
        self.assertEqual("send_to_test_completed", event.event_type)
        self.assertTrue(any(item.artifact_type == "send_to_test_stdout" for item in artifacts))
        self.assertTrue(any(item.artifact_type == "send_to_test_stderr" for item in artifacts))
        self.assertTrue(any(item.event_type == "send_to_test_completed" for item in events))

    def test_send_to_test_handoff_requires_mr_handoff_stage(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021D")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        with self.assertRaisesRegex(IntakeError, "must complete MR handoff"):
            self.coordinator.send_to_test_handoff(session_id=completed_session.id)

    def test_verification_passed_routes_to_doc_harvest_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021E",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021E")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("doc_harvest_requested", updated_session.current_stage)
        self.assertEqual("doc_harvest_requested", followup_event.event_type)

    def test_implementation_completed_routes_to_self_review_when_policy_required(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR1",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR1")

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        self.assertEqual("active", updated_session.status.value)
        self.assertEqual("self_review_requested", updated_session.current_stage)
        self.assertEqual("code-reviewer", updated_session.current_owner)
        self.assertEqual("self_review_requested", followup_event.event_type)

    def test_complete_self_review_passed_routes_to_verification(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR2",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR2")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, event, followup_event = self.coordinator.complete_self_review(
            session_id=session.id,
            outcome="passed",
            summary="Reviewed implementation and found no blocking issues.",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("self_review_passed", event.event_type)
        self.assertEqual("verification_requested", followup_event.event_type)
        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertTrue(any(item.artifact_type == "self_review_summary" for item in artifacts))

    def test_complete_self_review_with_issues_routes_to_implementer_correction(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR3",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR3")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )

        updated_session, event, followup_event = self.coordinator.complete_self_review(
            session_id=session.id,
            outcome="issues_found",
            summary="Found two naming issues and one missing guard branch.",
        )
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("self_review_issues_found", event.event_type)
        self.assertEqual("self_review_correction_requested", followup_event.event_type)
        self.assertEqual("self_review_correction_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
        self.assertTrue(any(item.work_type == "self_review_correction" for item in work_items))

    def test_self_review_correction_completed_reenters_verification_loop(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021SR4",
            workflow_profile="oneshot",
            policy={"self_review_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021SR4")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.complete_self_review(
            session_id=session.id,
            outcome="issues_found",
            summary="Found two naming issues and one missing guard branch.",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "self review fixes done"},
        )

        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_requested", followup_event.event_type)

    def test_complete_doc_harvest_marks_lane_completed(self) -> None:
        session, _, _ = self.coordinator.create_task_session(
            "IOS-30021F",
            workflow_profile="oneshot",
            policy={"doc_harvest_policy": "required"},
        )
        self.coordinator.prepare_task_session("IOS-30021F")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )

        updated_session, event = self.coordinator.complete_doc_harvest(
            session_id=session.id,
            summary="Feature README updated with current behavior.",
        )
        artifacts = self.artifact_repository.list_for_session(session.id)

        self.assertEqual("completed", updated_session.status.value)
        self.assertEqual("doc_harvest_completed", updated_session.current_stage)
        self.assertEqual("doc_harvest_completed", event.event_type)
        self.assertTrue(any(item.artifact_type == "doc_harvest_summary" for item in artifacts))

    def test_followup_implementation_completed_reenters_verification_loop(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30022")
        self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "done"},
        )
        completed_session, _ = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="verification_passed",
            payload={"summary": "all green"},
        )
        self.coordinator.reopen_from_qa(
            session_id=completed_session.id,
            comment_text="QA: still failing on edge case",
        )

        updated_session, followup_event = self.coordinator.handle_operator_event(
            session_id=session.id,
            event_type="implementation_completed",
            payload={"summary": "qa fix done"},
        )

        self.assertEqual("verification_requested", updated_session.current_stage)
        self.assertEqual("verification-coordinator", updated_session.current_owner)
        self.assertEqual("verification_requested", followup_event.event_type)

    def test_resume_session_reactivates_escalated_work_item(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30019")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        escalated_session, _, _ = self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        events = self.event_repository.list_for_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)
        work_items = self.work_item_repository.list_for_session(session.id)

        self.assertEqual("waiting_for_operator", escalated_session.status.value)
        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("implementer", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(1, len(work_items))
        self.assertEqual("assigned", work_items[0].status.value)
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30019.", sent_inputs[-1])
        self.assertTrue(any(item.event_type == "session_resumed_by_operator" for item in events))

    def test_resume_session_requires_waiting_for_operator_status(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30020")

        with self.assertRaisesRegex(IntakeError, "not resumable"):
            self.coordinator.resume_session(session.id)

    def test_resume_session_reactivates_paused_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30021")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.coordinator.pause_session(session.id)

        resumed_session, resumed_event, dispatch_event = self.coordinator.resume_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("active", resumed_session.status.value)
        self.assertEqual("implementer", resumed_session.current_owner)
        self.assertEqual("session_resumed_by_operator", resumed_event.event_type)
        self.assertEqual("paused", resumed_event.payload["resume_reason"])
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(2, len(sent_inputs))

    def test_retry_session_creates_new_work_item_for_escalated_session(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30022")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        retried_session, retried_event, dispatch_event = self.coordinator.retry_session(session.id)
        work_items = self.work_item_repository.list_for_session(session.id)
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("active", retried_session.status.value)
        self.assertEqual("implementer", retried_session.current_owner)
        self.assertEqual("session_retried_by_operator", retried_event.event_type)
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(2, len(work_items))
        self.assertEqual(
            ["assigned", "waiting_for_operator"],
            sorted(item.status.value for item in work_items),
        )
        self.assertTrue(
            any(
                item.title.startswith("Retry: ") and item.status.value == "assigned"
                for item in work_items
            )
        )
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30022.", sent_inputs[-1])

    def test_redirect_session_reroutes_escalated_work_item_to_allowed_role(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30023")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        shadow_role = self.role_repository.create(
            session_id=session.id,
            role_name="implementer-shadow",
            runtime_backend="recording",
            runtime_handle="recording:implementer-shadow",
        )
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )
        ALLOWED_STAGE_ROLE_TARGETS["implementation_requested"].add("implementer-shadow")
        try:
            redirected_session, redirected_event, dispatch_event = self.coordinator.redirect_session(
                session_id=session.id,
                target_role_name="implementer-shadow",
            )
        finally:
            ALLOWED_STAGE_ROLE_TARGETS["implementation_requested"].remove("implementer-shadow")
        work_items = self.work_item_repository.list_for_session(session.id)
        shadow_inputs = self.session_backend.get_sent_inputs(shadow_role.runtime_handle)

        self.assertEqual("active", redirected_session.status.value)
        self.assertEqual("implementer-shadow", redirected_session.current_owner)
        self.assertEqual("session_redirected_by_operator", redirected_event.event_type)
        self.assertEqual("role_input_dispatched", dispatch_event.event_type)
        self.assertEqual(2, len(work_items))
        self.assertTrue(
            any(
                item.title.startswith("Redirect to implementer-shadow:")
                and item.status.value == "assigned"
                for item in work_items
            )
        )
        self.assertTrue(
            any(
                item.owner_role_id == implementer_role.id and item.status.value == "waiting_for_operator"
                for item in work_items
            )
        )
        self.assertEqual(1, len(shadow_inputs))
        self.assertIn("Start implementation work for IOS-30023.", shadow_inputs[-1])

    def test_redirect_session_rejects_role_not_allowed_for_stage(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30024")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        with self.assertRaisesRegex(IntakeError, "not allowed for stage"):
            self.coordinator.redirect_session(
                session_id=session.id,
                target_role_name="verification-coordinator",
            )

    def test_redirect_session_requires_different_target_role(self) -> None:
        session, _, _, _ = self.coordinator.prepare_task_session("IOS-30025")
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        self.session_backend.simulate_output(
            implementer_role.runtime_handle,
            'SDD_ERROR: {"summary":"tool failed","details":"command exited 1"}',
        )
        self.coordinator.collect_role_output(
            session_id=session.id,
            role_name="implementer",
        )

        with self.assertRaisesRegex(IntakeError, "must differ"):
            self.coordinator.redirect_session(
                session_id=session.id,
                target_role_name="implementer",
            )


if __name__ == "__main__":
    unittest.main()
