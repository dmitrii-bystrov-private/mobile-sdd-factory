from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from backend.session_backend.runtime_models import RuntimeRoleHandle
from backend.session_backend.tmux_backend import TmuxSessionBackend


class TmuxBackendTests(unittest.TestCase):
    def _wait_for_output(
        self,
        backend: TmuxSessionBackend,
        role,
        *,
        timeout_seconds: float = 1.0,
        expected_substring: str | None = None,
    ) -> str:
        deadline = time.time() + timeout_seconds
        collected = ""
        while time.time() < deadline:
            text = "".join(chunk.text for chunk in backend.read_output(role))
            if text:
                collected += text
                if expected_substring is None or expected_substring in collected:
                    return collected
            time.sleep(0.05)
        return collected

    def test_recording_mode_tracks_sent_inputs_without_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = TmuxSessionBackend(
                mode="recording",
                runtime_root=Path(temp_dir),
            )
            session = backend.create_task_session("IOS-50000")
            role = backend.spawn_role(session, "implementer")

            backend.send_input(role, "hello world")

            self.assertEqual("recording", backend.effective_mode)
            self.assertEqual(["hello world"], backend.get_sent_inputs(role.role_id))

    def test_recording_mode_returns_simulated_output_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = TmuxSessionBackend(
                mode="recording",
                runtime_root=Path(temp_dir),
            )
            session = backend.create_task_session("IOS-50001")
            role = backend.spawn_role(session, "implementer")

            backend.simulate_output(role.role_id, "first line")
            backend.simulate_output(role.role_id, "second line")

            chunks = backend.read_output(role)

            self.assertEqual(["first line", "second line"], [chunk.text for chunk in chunks])
            self.assertEqual([], backend.read_output(role))

    def test_tmux_mode_sets_explicit_session_size_with_env_override(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        previous_width = os.environ.get("SDD_FACTORY_TMUX_WIDTH")
        previous_height = os.environ.get("SDD_FACTORY_TMUX_HEIGHT")
        os.environ["SDD_FACTORY_TMUX_WIDTH"] = "240"
        os.environ["SDD_FACTORY_TMUX_HEIGHT"] = "70"
        try:
            backend = FakeTmuxBackend()
            session = backend.create_task_session("IOS-50001TMUXSIZE")
        finally:
            if previous_width is None:
                os.environ.pop("SDD_FACTORY_TMUX_WIDTH", None)
            else:
                os.environ["SDD_FACTORY_TMUX_WIDTH"] = previous_width
            if previous_height is None:
                os.environ.pop("SDD_FACTORY_TMUX_HEIGHT", None)
            else:
                os.environ["SDD_FACTORY_TMUX_HEIGHT"] = previous_height

        self.assertEqual("sdd-IOS-50001TMUXSIZE", session.session_id)
        self.assertEqual(
            [
                (
                    "new-session",
                    "-d",
                    "-x",
                    "240",
                    "-y",
                    "70",
                    "-s",
                    "sdd-IOS-50001TMUXSIZE",
                    "sh",
                )
            ],
            backend.calls,
        )

    def test_tmux_launcher_prompt_echo_does_not_resubmit_input(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:implementer",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_role_ready[role.role_id] = True

        backend.send_input(role, "first routed work")
        backend._handle_tmux_interactive_driver_output(role.role_id, "❯ first routed work")

        submit_calls = [call for call in backend.calls if call[-1] == "C-m"]
        self.assertEqual([("send-keys", "-t", role.role_id, "C-m")], submit_calls)

    def test_normalize_terminal_text_strips_ansi_noise(self) -> None:
        backend = TmuxSessionBackend(mode="recording")
        noisy = (
            "\x1b[1CQuick\x1b[1Csafety\x1b[1Ccheck:\x1b[1CIs\x1b[1Cthis\x1b[1Ca\x1b[1Cproject\n"
            "\x1b]8;id=zaxmda;https://code.claude.com/docs/en/security\x07Security guide\x1b]8;;\x07\n"
            "\x1b[1CEnter\x1b[1Cto\x1b[1Cconfirm\x1b[1C·\x1b[1CEsc\x1b[1Cto\x1b[1Ccancel\n"
        )
        normalized = backend._normalize_terminal_text(noisy)
        self.assertIn("quick safety check", normalized)
        self.assertIn("enter to confirm", normalized)
        self.assertIn("esc to cancel", normalized)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_keeps_persistent_subprocess_across_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50002TMUX")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "persistent_echo_agent.py"
            )
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=runtime_root / "IOS-50002TMUX" / "runtime" / "role-workspaces" / "implementer",
                launch_command=["python3", "-u", str(fixture)],
            )

            startup = self._wait_for_output(
                backend,
                role,
                timeout_seconds=2.0,
                expected_substring="AGENT_READY",
            )
            self.assertIn("AGENT_READY", startup)

            backend.send_input(role, "first routed work")
            first_round = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring="round 1",
            )
            self.assertIn("round 1", first_round)
            self.assertIn("SDD_OUTPUT", first_round)

            backend.send_input(role, "second routed work")
            second_round = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring="round 2",
            )
            self.assertIn("round 2", second_round)
            self.assertIn("SDD_OUTPUT", second_round)

            self.assertEqual("tmux", backend.effective_mode)
            backend.stop_session(session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_buffers_launcher_backed_input_until_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50004TMUX")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_launcher_fixture.py"
            )
            role_workspace = runtime_root / "IOS-50004TMUX" / "runtime" / "role-workspaces" / "implementer"
            role_workspace.mkdir(parents=True, exist_ok=True)
            launcher_script = role_workspace / "launch-role.sh"
            launcher_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        f"exec python3 -u {fixture}",
                        "",
                    ]
                )
            )
            launcher_script.chmod(0o755)
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=role_workspace,
                launch_command=[str(launcher_script)],
            )

            backend.send_input(role, "first routed work")

            interactive_round = self._wait_for_output(
                backend,
                role,
                timeout_seconds=4.0,
                expected_substring="interactive round done",
            )
            self.assertIn("Quick safety check", interactive_round)
            self.assertIn("✻ Brewed for 1s", interactive_round)
            self.assertIn("ROUTED:first routed work", interactive_round)
            self.assertIn("SDD_OUTPUT", interactive_round)
            self.assertEqual(["first routed work"], backend.get_sent_inputs(role.role_id))

            backend.stop_session(session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_materializes_multiline_routed_input_for_launcher_backed_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50004B")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_launcher_fixture.py"
            )
            role_workspace = runtime_root / "IOS-50004B" / "runtime" / "role-workspaces" / "implementer"
            role_workspace.mkdir(parents=True, exist_ok=True)
            launcher_script = role_workspace / "launch-role.sh"
            launcher_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        f"exec python3 -u {fixture}",
                        "",
                    ]
                )
            )
            launcher_script.chmod(0o755)
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=role_workspace,
                launch_command=[str(launcher_script)],
            )

            multiline = "line 1\nline 2\nline 3"
            backend.send_input(role, multiline)

            routed = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring="ROUTED:Read ROUTED_WORK.md",
            )
            routed_input_path = role_workspace / "ROUTED_WORK.md"
            self.assertTrue(routed_input_path.is_file())
            self.assertEqual(multiline, routed_input_path.read_text())
            self.assertIn("ROUTED:Read ROUTED_WORK.md", routed)

            backend.stop_session(session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_emits_synthetic_selection_error_for_launcher_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50005")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_selection_blocker_fixture.py"
            )
            role_workspace = runtime_root / "IOS-50005" / "runtime" / "role-workspaces" / "implementer"
            role_workspace.mkdir(parents=True, exist_ok=True)
            launcher_script = role_workspace / "launch-role.sh"
            launcher_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        f"exec python3 -u {fixture}",
                        "",
                    ]
                )
            )
            launcher_script.chmod(0o755)
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=role_workspace,
                launch_command=[str(launcher_script)],
            )

            blocker_output = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring='SDD_ERROR: {"summary":"interactive selection required"',
            )
            self.assertIn("Quick safety check", blocker_output)
            self.assertIn("✻ Brewed for 1s", blocker_output)
            self.assertIn("Enter to select", blocker_output)
            self.assertIn('SDD_ERROR: {"summary":"interactive selection required"', blocker_output)

            backend.stop_session(session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_emits_second_confirmation_blocker_after_operator_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50007")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_multistep_fixture.py"
            )
            role_workspace = runtime_root / "IOS-50007" / "runtime" / "role-workspaces" / "implementer"
            role_workspace.mkdir(parents=True, exist_ok=True)
            launcher_script = role_workspace / "launch-role.sh"
            launcher_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        f"exec python3 -u {fixture}",
                        "",
                    ]
                )
            )
            launcher_script.chmod(0o755)
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=role_workspace,
                launch_command=[str(launcher_script)],
            )

            first_blocker = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring='SDD_ERROR: {"summary":"interactive selection required"',
            )
            self.assertIn('SDD_ERROR: {"summary":"interactive selection required"', first_blocker)

            backend.send_input(role, "1")

            second_blocker = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring='SDD_ERROR: {"summary":"interactive confirmation required"',
            )
            self.assertIn("AUTH_CONTINUED:1", second_blocker)
            self.assertIn('SDD_ERROR: {"summary":"interactive confirmation required"', second_blocker)

            backend.send_input(role, "1")
            completion = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring="interactive multi-step recovery completed",
            )
            result_path = role_workspace / "RESULT.json"
            self.assertIn("CONFIRM_CONTINUED:1", completion)
            self.assertTrue(result_path.is_file())
            self.assertIn("interactive multi-step recovery completed", result_path.read_text())

            backend.stop_session(session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_keeps_buffered_work_during_unknown_pre_ready_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50008")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_unknown_pre_ready_fixture.py"
            )
            role_workspace = runtime_root / "IOS-50008" / "runtime" / "role-workspaces" / "implementer"
            role_workspace.mkdir(parents=True, exist_ok=True)
            launcher_script = role_workspace / "launch-role.sh"
            launcher_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        f"exec python3 -u {fixture}",
                        "",
                    ]
                )
            )
            launcher_script.chmod(0o755)
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=role_workspace,
                launch_command=[str(launcher_script)],
            )

            backend.send_input(role, "first routed work")

            pre_ready_output = self._wait_for_output(
                backend,
                role,
                timeout_seconds=1.5,
                expected_substring="SDD_FACTORY_AGENT_BOOTSTRAP",
            )
            self.assertIn("SDD_FACTORY_AGENT_BOOTSTRAP", pre_ready_output)
            self.assertNotIn("SDD_OUTPUT", pre_ready_output)
            self.assertFalse(backend.tmux_role_ready[role.role_id])
            self.assertEqual(["first routed work"], backend.tmux_buffered_inputs[role.role_id])

            backend.stop_session(session)

    def test_ansi_normalized_prompt_detection_helpers(self) -> None:
        backend = TmuxSessionBackend(mode="recording")
        trust = backend._normalize_terminal_text(
            "\x1b[1CQuick\x1b[1Csafety\x1b[1Ccheck\x1b[1Ctrust\x1b[1Cthis\x1b[1Cfolder"
        )
        selection = backend._normalize_terminal_text(
            "☐ Action\nWhat would you like to do?\n❯ 1. Option 1\n2. Option 2\nEnter to select · ↑/↓ to navigate · Esc to cancel"
        )
        confirmation = backend._normalize_terminal_text(
            "Confirm tool execution?\nEnter to confirm · Esc to cancel"
        )
        status_signal = backend._normalize_terminal_text(
            "❯ .\n\n✻ Churned for 5s"
        )
        status_signal_long = backend._normalize_terminal_text(
            "❯ .\n\n✻ Brewed for 1m 24s"
        )
        prompt_ready = backend._normalize_terminal_text(
            "❯ Try \"refactor <filepath>\"\n[Sonnet 4.6] 0% | $0.00 | 0m 2s"
        )
        codex_prompt_ready = backend._normalize_terminal_text(
            "› Summarize recent commits\n\ngpt-5.5 medium · ~/repo"
        )

        self.assertTrue(backend._contains_workspace_trust_prompt(trust))
        self.assertTrue(backend._contains_generic_selection_blocker(selection))
        self.assertTrue(backend._contains_generic_confirmation_blocker(confirmation))
        self.assertTrue(backend._contains_runner_status_signal(status_signal))
        self.assertTrue(backend._contains_runner_ready_prompt(status_signal))
        self.assertTrue(backend._contains_runner_status_signal(status_signal_long))
        self.assertTrue(backend._contains_runner_ready_prompt(status_signal_long))
        self.assertTrue(backend._contains_interactive_input_prompt(prompt_ready))
        self.assertTrue(backend._contains_runner_ready_prompt(prompt_ready))
        self.assertTrue(backend._contains_interactive_input_prompt(codex_prompt_ready))
        self.assertTrue(backend._contains_runner_ready_prompt(codex_prompt_ready))
        self.assertFalse(backend._contains_interactive_input_prompt(trust))
        self.assertFalse(backend._contains_interactive_input_prompt(selection))
        self.assertFalse(backend._contains_interactive_input_prompt(confirmation))

    def test_mcp_availability_blocker_details_extracts_servers(self) -> None:
        backend = TmuxSessionBackend(mode="recording")
        details = backend._build_mcp_availability_blocker_details(
            "⚠ mcp client for `android-rag` failed to start "
            "⚠ mcp client for `frontend-rag` failed to start "
            "⚠ mcp startup incomplete (failed: android-rag, frontend-rag, ios-rag)"
        )

        self.assertIsNotNone(details)
        assert details is not None
        self.assertIn("android-rag", details)
        self.assertIn("frontend-rag", details)
        self.assertIn("ios-rag", details)
        self.assertIn("Resume Session", details)


if __name__ == "__main__":
    unittest.main()
