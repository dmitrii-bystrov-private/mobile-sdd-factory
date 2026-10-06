from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.acceptance.run_roots import (
    cleanup_runner_test_residue_for_run_root,
    cleanup_stale_run_roots,
    cleanup_stale_runner_test_residue,
    run_active_marker,
    run_tmux_socket_root,
)


class AcceptanceRunRootsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name) / "repo"
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self.home_root = Path(self.temp_dir.name) / "home"
        self.home_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cleanup_stale_runner_test_residue_removes_old_test_scoped_runner_files(self) -> None:
        claude_test_dir = (
            self.home_root
            / ".claude"
            / "projects"
            / "-Users-test-mobile-sdd-factory--runtime-test-runs-old-workdir-IOS-ACCEPT-001-runtime-role-workspaces-implementer"
        )
        claude_test_dir.mkdir(parents=True, exist_ok=True)
        (claude_test_dir / "session.jsonl").write_text("{}\n")

        claude_project_dir = (
            self.home_root / ".claude" / "projects" / "-Users-test-mobile-sdd-factory"
        )
        claude_project_dir.mkdir(parents=True, exist_ok=True)

        codex_session_dir = self.home_root / ".codex" / "sessions" / "2026" / "05" / "17"
        codex_session_dir.mkdir(parents=True, exist_ok=True)
        codex_test_file = codex_session_dir / "test.jsonl"
        codex_test_file.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "cwd": str(
                            self.repo_root / ".runtime" / "test-runs" / "sdd-factory-old" / "workdir"
                        )
                    },
                }
            )
            + "\n"
        )
        codex_regular_file = codex_session_dir / "regular.jsonl"
        codex_regular_file.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"cwd": str(self.repo_root / "workdir" / "IOS-99999")},
                }
            )
            + "\n"
        )

        with patch("factory.acceptance.run_roots.Path.home", return_value=self.home_root):
            cleanup_stale_runner_test_residue(self.repo_root)

        self.assertFalse(claude_test_dir.exists())
        self.assertTrue(claude_project_dir.exists())
        self.assertFalse(codex_test_file.exists())
        self.assertTrue(codex_regular_file.exists())

    def test_cleanup_runner_test_residue_for_run_root_removes_only_current_run_residue(self) -> None:
        run_root = self.repo_root / ".runtime" / "test-runs" / "sdd-factory-runtime-management.abcd1234"
        run_root.mkdir(parents=True, exist_ok=True)

        matching_claude_dir = (
            self.home_root
            / ".claude"
            / "projects"
            / "-Users-test-mobile-sdd-factory--runtime-test-runs-sdd-factory-runtime-management-abcd1234-workdir-IOS-ACCEPT-001-runtime-role-workspaces-implementer"
        )
        matching_claude_dir.mkdir(parents=True, exist_ok=True)

        other_claude_dir = (
            self.home_root
            / ".claude"
            / "projects"
            / "-Users-test-mobile-sdd-factory--runtime-test-runs-sdd-factory-runtime-management-zzzz9999-workdir-IOS-ACCEPT-002-runtime-role-workspaces-implementer"
        )
        other_claude_dir.mkdir(parents=True, exist_ok=True)

        codex_session_dir = self.home_root / ".codex" / "sessions" / "2026" / "05" / "17"
        codex_session_dir.mkdir(parents=True, exist_ok=True)
        matching_codex_file = codex_session_dir / "matching.jsonl"
        matching_codex_file.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "cwd": str(run_root / "workdir" / "IOS-ACCEPT-001" / "runtime")
                    },
                }
            )
            + "\n"
        )
        other_codex_file = codex_session_dir / "other.jsonl"
        other_codex_file.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "cwd": str(
                            self.repo_root
                            / ".runtime"
                            / "test-runs"
                            / "sdd-factory-runtime-management.zzzz9999"
                            / "workdir"
                            / "IOS-ACCEPT-002"
                            / "runtime"
                        )
                    },
                }
            )
            + "\n"
        )

        with patch("factory.acceptance.run_roots.Path.home", return_value=self.home_root):
            cleanup_runner_test_residue_for_run_root(self.repo_root, run_root)

        self.assertFalse(matching_claude_dir.exists())
        self.assertTrue(other_claude_dir.exists())
        self.assertFalse(matching_codex_file.exists())
        self.assertTrue(other_codex_file.exists())

    def test_cleanup_stale_run_roots_keeps_active_run_root(self) -> None:
        runs_root = self.repo_root / ".runtime" / "test-runs"
        active_run = runs_root / "sdd-factory-runtime-management.active1234"
        stale_run = runs_root / "sdd-factory-runtime-management.stale5678"
        active_run.mkdir(parents=True, exist_ok=True)
        stale_run.mkdir(parents=True, exist_ok=True)

        active_socket_root = run_tmux_socket_root(active_run)
        stale_socket_root = run_tmux_socket_root(stale_run)
        active_socket_root.mkdir(parents=True, exist_ok=True)
        stale_socket_root.mkdir(parents=True, exist_ok=True)
        run_active_marker(active_run).write_text(json.dumps({"pid": os.getpid()}))
        run_active_marker(stale_run).write_text(json.dumps({"pid": 999999}))

        with patch("factory.acceptance.run_roots.subprocess.run") as mocked_run:
            cleanup_stale_run_roots(self.repo_root)

        self.assertTrue(active_run.exists())
        self.assertTrue(active_socket_root.exists())
        self.assertFalse(stale_run.exists())
        self.assertFalse(stale_socket_root.exists())
        mocked_run.assert_not_called()
