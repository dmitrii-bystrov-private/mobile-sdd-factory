from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "write-result.py"


class WriteResultScriptTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_code_scout_clean_result_is_minimal_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "code-scout",
                "--output",
                str(output_path),
                "--work-item-id",
                "11",
                "--result",
                "clean",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "output_type": "completed",
                    "payload": {
                        "work_item_id": 11,
                        "result": "clean",
                    },
                },
                payload,
            )

    def test_code_scout_findings_require_count_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "code-scout",
                "--output",
                str(output_path),
                "--work-item-id",
                "12",
                "--result",
                "findings_found",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("--findings-path", result.stderr)

    def test_verification_failed_result_requires_explicit_failure_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "verification-coordinator",
                "--output",
                str(output_path),
                "--work-item-id",
                "481",
                "--result",
                "failed",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("--failure or --summary", result.stderr)

    def test_verification_failed_result_writes_minimal_valid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "verification-coordinator",
                "--output",
                str(output_path),
                "--work-item-id",
                "481",
                "--result",
                "failed",
                "--failure",
                "build-for-testing failed",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", payload["output_type"])
            self.assertEqual(481, payload["payload"]["work_item_id"])
            self.assertEqual("failed", payload["payload"]["result"])
            self.assertEqual(["build-for-testing failed"], payload["payload"]["failures"])

    def test_verification_blocked_cycle_does_not_require_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "verification-coordinator",
                "--output",
                str(output_path),
                "--work-item-id",
                "482",
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
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "code-reviewer",
                "--output",
                str(output_path),
                "--work-item-id",
                "210",
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

    def test_story_planning_blocked_result_can_carry_operator_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "requirements-clarifier-worker",
                "--output",
                str(output_path),
                "--work-item-id",
                "31",
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
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "doc-harvest-worker",
                "--output",
                str(output_path),
                "--work-item-id",
                "91",
                "--summary",
                "README updated",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", payload["output_type"])
            self.assertEqual(91, payload["payload"]["work_item_id"])
            self.assertEqual("README updated", payload["payload"]["summary"])

    def test_spec_verifier_failed_result_can_carry_blocker_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "spec-verifier-worker",
                "--output",
                str(output_path),
                "--work-item-id",
                "41",
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
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "implementer",
                "--output",
                str(output_path),
                "--work-item-id",
                "501",
                "--subtask-key",
                "IOS-55555",
                "--summary",
                "implemented subtask",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("completed", payload["output_type"])
            self.assertEqual("IOS-55555", payload["payload"]["subtask_key"])

    def test_bug_fixer_completed_result_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "bug-fixer",
                "--output",
                str(output_path),
                "--work-item-id",
                "601",
                "--summary",
                "bug fixed",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(601, payload["payload"]["work_item_id"])

    def test_mr_comments_analyst_completed_result_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "RESULT.json"
            result = self._run(
                "mr-comments-analyst-worker",
                "--output",
                str(output_path),
                "--work-item-id",
                "701",
                "--summary",
                "mr comments triaged",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("mr comments triaged", payload["payload"]["summary"])
