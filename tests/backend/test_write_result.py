from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.models.enums import WorkItemStatus
from backend.state.db import Database
from backend.state.role_repository import RoleRepository
from backend.state.session_repository import SessionRepository
from backend.state.work_item_repository import WorkItemRepository


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "write-result.py"
SHELL_SCRIPT_PATH = REPO_ROOT / "scripts" / "write-result.sh"


class WriteResultScriptTests(unittest.TestCase):
    def _create_context(self, temp_dir: str, *, role_name: str, work_type: str = "generic") -> tuple[dict[str, str], Path, int]:
        workdir_root = Path(temp_dir) / "workdir"
        database_path = workdir_root / "factory.sqlite3"
        database = Database(database_path)
        database.initialize()

        sessions = SessionRepository(database)
        roles = RoleRepository(database)
        work_items = WorkItemRepository(database)

        session = sessions.create(
            task_key="IOS-12345",
            current_stage="verification_requested",
            workflow_profile="legacy",
            policy={},
        )
        role = roles.create(
            session_id=session.id,
            role_name=role_name,
            runtime_backend="tmux",
        )
        work_item = work_items.create(
            session_id=session.id,
            work_type=work_type,
            title=f"{role_name} item",
            owner_role_id=role.id,
            status=WorkItemStatus.ASSIGNED,
        )
        output_path = workdir_root / "IOS-12345" / "runtime" / "role-workspaces" / role_name / "RESULT.json"
        env = dict(os.environ)
        env["SDD_FACTORY_DB_PATH"] = str(database_path)
        env["SDD_FACTORY_WORKDIR_ROOT"] = str(workdir_root)
        env["SDD_FACTORY_ROLE_NAME"] = role_name
        return env, output_path, int(work_item.id or 0)

    def _run(self, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_code_scout_clean_result_is_minimal_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="code-scout")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--result",
                "clean",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": work_item_id,
                        "result": "clean",
                    },
                },
                payload,
            )

    def test_code_scout_findings_require_count_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, _, work_item_id = self._create_context(temp_dir, role_name="code-scout")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--result",
                "findings_found",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("--findings-path", result.stderr)

    def test_verification_failed_result_requires_explicit_failure_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, _, work_item_id = self._create_context(temp_dir, role_name="verification-coordinator")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--result",
                "failed",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("--failure or --summary", result.stderr)

    def test_verification_failed_result_writes_minimal_valid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="verification-coordinator")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--result",
                "failed",
                "--failure",
                "build-for-testing failed",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", payload["output_type"])
            self.assertEqual(work_item_id, payload["payload"]["work_item_id"])
            self.assertEqual("failed", payload["payload"]["result"])
            self.assertEqual(["build-for-testing failed"], payload["payload"]["failures"])

    def test_verification_blocked_cycle_does_not_require_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="verification-coordinator")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "blocked_verification_cycle",
                "--summary",
                "verification cycle blocked",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("blocked_verification_cycle", payload["output_type"])
            self.assertNotIn("result", payload["payload"])

    def test_code_reviewer_failed_result_can_include_issues_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="code-reviewer")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "failed",
                "--summary",
                "review issues found",
                "--issues-markdown",
                "Issue 1",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", payload["output_type"])
            self.assertEqual("Issue 1", payload["payload"]["issues_markdown"])

    def test_code_reviewer_failed_result_can_read_issues_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="code-reviewer")
            issues_path = Path(temp_dir) / "issues.md"
            issues_path.write_text(
                "- `FinomCore/FinomCore/App Core/Service.swift`: `handleActivation()` issue\n",
                encoding="utf-8",
            )

            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "failed",
                "--summary",
                "review issues found",
                "--issues-markdown-file",
                str(issues_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", payload["output_type"])
            self.assertEqual(issues_path.read_text(encoding="utf-8").strip(), payload["payload"]["issues_markdown"])

    def test_code_reviewer_failed_result_rejects_inline_and_file_issues_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, _output_path, work_item_id = self._create_context(temp_dir, role_name="code-reviewer")
            issues_path = Path(temp_dir) / "issues.md"
            issues_path.write_text("- Issue 1\n", encoding="utf-8")

            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "failed",
                "--summary",
                "review issues found",
                "--issues-markdown",
                "Issue 1",
                "--issues-markdown-file",
                str(issues_path),
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("Use either --issues-markdown or --issues-markdown-file", result.stderr)

    def test_code_reviewer_passed_result_tolerates_zero_findings_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="code-reviewer")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "passed",
                "--summary",
                "No findings in self-review pass.",
                "--findings-count",
                "0",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("passed", payload["output_type"])
            self.assertEqual(
                {
                    "work_item_id": work_item_id,
                    "summary": "No findings in self-review pass.",
                },
                payload["payload"],
            )

    def test_code_scout_findings_reject_zero_findings_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, _, work_item_id = self._create_context(temp_dir, role_name="code-scout")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--result",
                "findings_found",
                "--findings-count",
                "0",
                "--findings-path",
                "/tmp/findings.md",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("positive --findings-count", result.stderr)

    def test_story_planning_blocked_result_can_carry_operator_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(
                temp_dir,
                role_name="requirements-clarifier-worker",
            )
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "failed",
                "--summary",
                "requirements clarification needed",
                "--needs-operator-input",
                "--missing-input",
                "backend API response shape",
                "--pending-decision",
                "choose option A or B",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", payload["output_type"])
            self.assertEqual(True, payload["payload"]["needs_operator_input"])
            self.assertEqual(["backend API response shape"], payload["payload"]["missing_inputs"])
            self.assertEqual(["choose option A or B"], payload["payload"]["pending_decisions"])

    def test_doc_harvest_completed_result_is_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="doc-harvest-worker")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--summary",
                "README updated",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", payload["output_type"])
            self.assertEqual(work_item_id, payload["payload"]["work_item_id"])
            self.assertEqual("README updated", payload["payload"]["summary"])

    def test_spec_verifier_failed_result_can_carry_blocker_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="spec-verifier-worker")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "failed",
                "--summary",
                "planning blockers remain",
                "--blocker-question",
                "Should cleanup include literals too?",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", payload["output_type"])
            self.assertEqual(
                ["Should cleanup include literals too?"],
                payload["payload"]["blocker_questions"],
            )

    def test_implementer_completed_result_can_carry_subtask_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="implementer")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--subtask-key",
                "IOS-55555",
                "--summary",
                "implemented subtask",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", payload["output_type"])
            self.assertEqual("IOS-55555", payload["payload"]["subtask_key"])

    def test_shell_helper_does_not_fallback_to_file_when_ingress_transport_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(
                temp_dir,
                role_name="verification-coordinator",
            )
            env["SDD_FACTORY_BACKEND_PORT"] = "1"
            result = subprocess.run(
                [
                    "bash",
                    str(SHELL_SCRIPT_PATH),
                    "--work-item-id",
                    str(work_item_id),
                    "--result",
                    "passed",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(10, result.returncode)
            self.assertIn("SDD_RESULT_INGRESS_ERROR", result.stderr)
            self.assertFalse(output_path.exists())

    def test_bug_fixer_completed_result_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="bug-fixer")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--summary",
                "bug fixed",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(work_item_id, payload["payload"]["work_item_id"])

    def test_implementer_failed_result_can_request_operator_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(temp_dir, role_name="implementer")
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--output-type",
                "failed",
                "--summary",
                "review correction conflicts with accepted product direction",
                "--details",
                "Operator decision is required before continuing this correction pass.",
                "--needs-operator-input",
                "--conflict-point",
                "Reviewer asked for a revert that would restore the old warning haptic.",
                "--reviewer-premise",
                "The review assumes wrong-PIN should still map to warning.",
                "--preferred-direction",
                "Keep the .error mapping and remove the stale revert request.",
                "--requested-decision",
                "Confirm whether the accepted task direction still requires .error.",
                "--supporting-evidence",
                "The current acceptance criteria and follow-up task both require failed actions to map to .error.",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("failed", payload["output_type"])
            self.assertEqual(True, payload["payload"]["needs_operator_input"])
            self.assertEqual(
                "Reviewer asked for a revert that would restore the old warning haptic.",
                payload["payload"]["conflict_point"],
            )
            self.assertEqual(
                "The review assumes wrong-PIN should still map to warning.",
                payload["payload"]["reviewer_premise"],
            )
            self.assertEqual(
                "Keep the .error mapping and remove the stale revert request.",
                payload["payload"]["preferred_direction"],
            )
            self.assertEqual(
                "Confirm whether the accepted task direction still requires .error.",
                payload["payload"]["requested_decision"],
            )

    def test_mr_comments_analyst_completed_result_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, output_path, work_item_id = self._create_context(
                temp_dir,
                role_name="mr-comments-analyst-worker",
            )
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--summary",
                "comments processed",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("comments processed", payload["payload"]["summary"])
            self.assertEqual(work_item_id, payload["payload"]["work_item_id"])

    def test_rejects_work_item_from_other_runtime_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env, _, work_item_id = self._create_context(temp_dir, role_name="code-scout")
            env["SDD_FACTORY_ROLE_NAME"] = "verification-coordinator"
            result = self._run(
                env,
                "--work-item-id",
                str(work_item_id),
                "--result",
                "clean",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("not current runtime", result.stderr)
