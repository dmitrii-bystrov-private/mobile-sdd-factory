from pathlib import Path
import tempfile
import unittest

from backend.api.sse import SessionEventBus
from backend.coordinator.intake import IntakeError
from backend.coordinator.service import CoordinatorService
from backend.roles.contracts import ALLOWED_STAGE_ROLE_TARGETS, DEFAULT_SESSION_ROLES
from backend.session_backend.tmux_backend import TmuxSessionBackend
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

    def send_to_test(self, task_key: str) -> CommandResult:
        return CommandResult(
            command=["send_to_test", task_key],
            returncode=0,
            stdout=f"Done: {task_key} -> Ready for test\n",
            stderr="",
        )


class FakeSnapshotAdapter:
    def run(self, task_key: str) -> CommandResult:
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
        self.session_backend = TmuxSessionBackend()
        self.event_bus = SessionEventBus()
        self.coordinator = CoordinatorService(
            session_repository=self.session_repository,
            role_repository=self.role_repository,
            event_repository=self.event_repository,
            artifact_repository=self.artifact_repository,
            work_item_repository=self.work_item_repository,
            session_backend=self.session_backend,
            default_roles=DEFAULT_SESSION_ROLES,
            jira_adapter=FakeJiraAdapter(),
            snapshot_adapter=FakeSnapshotAdapter(),
            gitlab_adapter=FakeGitLabAdapter(),
            artifacts_root=Path(self.temp_dir.name) / "artifacts",
            event_bus=self.event_bus,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

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
        self.assertEqual(DEFAULT_SESSION_ROLES, [role.role_name for role in roles])

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
        self.assertEqual(3, len(roles))

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
        implementer_role = self.role_repository.get_by_name(prepared_session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertTrue(created)
        self.assertFalse(prepared_created)
        self.assertEqual(session.id, prepared_session.id)
        self.assertEqual("task_prepared", event.event_type)
        self.assertEqual("bug_analysis_requested", details["followup_event_type"])
        self.assertEqual("bug_analysis_requested", prepared_session.current_stage)
        self.assertEqual("implementer", prepared_session.current_owner)
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
        self.assertIn("Analyze bug IOS-30002BUG before implementation.", sent_inputs[0])
        self.assertIn("Test policy for this session: required.", sent_inputs[0])

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
        implementer_role = self.role_repository.get_by_name(session.id, "implementer")
        sent_inputs = self.session_backend.get_sent_inputs(implementer_role.runtime_handle)

        self.assertEqual("implementation_requested", updated_session.current_stage)
        self.assertEqual("implementer", updated_session.current_owner)
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
        self.assertEqual(2, len(sent_inputs))
        self.assertIn("Start implementation work for IOS-30003BUG.", sent_inputs[-1])
        self.assertIn("Bug analysis summary: Likely missing state reset in coordinator", sent_inputs[-1])

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
            role_name="implementer",
            output_type="completed",
            payload={"summary": "Root cause isolated"},
        )
        events = self.event_repository.list_for_session(session.id)

        self.assertEqual("bug_analysis_completed", mapped_event.event_type)
        self.assertEqual("implementation_requested", followup_event.event_type)
        self.assertEqual("implementation_requested", updated_session.current_stage)
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
        self.assertEqual(3, role_count)
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
        self.assertIsNone(updated_session.current_owner)
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
