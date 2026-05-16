from pathlib import Path
import tempfile
import time
import unittest

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

    def test_process_mode_keeps_persistent_subprocess_across_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="process",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50002")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "persistent_echo_agent.py"
            )
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=runtime_root / "IOS-50002" / "runtime" / "role-workspaces" / "implementer",
                launch_command=["python3", "-u", str(fixture)],
            )

            time.sleep(0.1)
            startup_chunks = backend.read_output(role)
            self.assertTrue(any("AGENT_READY" in chunk.text for chunk in startup_chunks))

            backend.send_input(role, "first routed work")
            first_round = self._wait_for_output(
                backend,
                role,
                timeout_seconds=2.0,
                expected_substring="round 1",
            )
            self.assertIn("round 1", first_round)
            self.assertIn("SDD_OUTPUT", first_round)

            backend.send_input(role, "second routed work")
            second_round = self._wait_for_output(
                backend,
                role,
                timeout_seconds=2.0,
                expected_substring="round 2",
            )
            self.assertIn("round 2", second_round)
            self.assertIn("SDD_OUTPUT", second_round)

            self.assertEqual("process", backend.effective_mode)
            backend.stop_session(session)

    def test_pty_mode_keeps_persistent_subprocess_across_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="pty",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50003")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "persistent_echo_agent.py"
            )
            role = backend.spawn_role(
                session,
                "implementer",
                start_directory=runtime_root / "IOS-50003" / "runtime" / "role-workspaces" / "implementer",
                launch_command=["python3", "-u", str(fixture)],
            )

            startup = self._wait_for_output(backend, role, expected_substring="AGENT_READY")
            self.assertIn("AGENT_READY", startup)

            backend.send_input(role, "first routed work")
            first_round = self._wait_for_output(backend, role, expected_substring="round 1")
            self.assertIn("round 1", first_round)
            self.assertIn("SDD_OUTPUT", first_round)

            backend.send_input(role, "second routed work")
            second_round = self._wait_for_output(backend, role, expected_substring="round 2")
            self.assertIn("round 2", second_round)
            self.assertIn("SDD_OUTPUT", second_round)

            self.assertEqual("pty", backend.effective_mode)
            backend.stop_session(session)

    def test_pty_mode_buffers_launcher_backed_input_until_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="pty",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50004")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_launcher_fixture.py"
            )
            role_workspace = runtime_root / "IOS-50004" / "runtime" / "role-workspaces" / "implementer"
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
                timeout_seconds=3.0,
                expected_substring="interactive round done",
            )
            self.assertIn("Quick safety check", interactive_round)
            self.assertIn("auto mode on", interactive_round)
            self.assertIn("ROUTED:first routed work", interactive_round)
            self.assertIn("SDD_OUTPUT", interactive_round)
            self.assertEqual(["first routed work"], backend.get_sent_inputs(role.role_id))

            backend.stop_session(session)

    def test_pty_mode_emits_synthetic_auth_error_for_launcher_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="pty",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50005")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_auth_blocker_fixture.py"
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
                expected_substring='SDD_ERROR: {"summary":"interactive auth required"',
            )
            self.assertIn("Quick safety check", blocker_output)
            self.assertIn("auto mode on", blocker_output)
            self.assertIn('SDD_ERROR: {"summary":"interactive auth required"', blocker_output)

            backend.stop_session(session)

    def test_pty_mode_emits_second_confirmation_blocker_after_operator_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="pty",
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
                expected_substring='SDD_ERROR: {"summary":"interactive auth required"',
            )
            self.assertIn('SDD_ERROR: {"summary":"interactive auth required"', first_blocker)

            backend.send_input(role, "/mcp")

            second_blocker = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring='SDD_ERROR: {"summary":"interactive confirmation required"',
            )
            self.assertIn("AUTH_CONTINUED:/mcp", second_blocker)
            self.assertIn('SDD_ERROR: {"summary":"interactive confirmation required"', second_blocker)

            backend.send_input(role, "1")
            completion = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring="interactive multi-step recovery completed",
            )
            self.assertIn("CONFIRM_CONTINUED:1", completion)
            self.assertIn("SDD_OUTPUT", completion)

            backend.stop_session(session)

    def test_pty_mode_emits_generic_pre_ready_blocker_for_unknown_interactive_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="pty",
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

            blocker_output = self._wait_for_output(
                backend,
                role,
                timeout_seconds=3.0,
                expected_substring='SDD_ERROR: {"summary":"interactive operator input required"',
            )
            self.assertIn('SDD_ERROR: {"summary":"interactive operator input required"', blocker_output)
            self.assertIn("before ready:", blocker_output)
            self.assertIn("6 6 6", blocker_output)

            backend.stop_session(session)

    def test_ansi_normalized_prompt_detection_helpers(self) -> None:
        backend = TmuxSessionBackend(mode="recording")
        trust = backend._normalize_terminal_text(
            "\x1b[1CQuick\x1b[1Csafety\x1b[1Ccheck\x1b[1Ctrust\x1b[1Cthis\x1b[1Cfolder"
        )
        auth = backend._normalize_terminal_text(
            "\x1b[39C1\x1b[1Cclaude.ai\x1b[1Cconnector\x1b[1Cneeds\x1b[1Cauth\x1b[1C·\x1b[1C/mcp"
        )
        confirmation = backend._normalize_terminal_text(
            "Confirm tool execution?\nEnter to confirm · Esc to cancel"
        )
        ready = backend._normalize_terminal_text(
            "❯  try \"fix lint errors\"\n⏵⏵ auto mode on (shift+tab to cycle) ◐ medium · /effort [sonnet 4.6]"
        )
        status_signal = backend._normalize_terminal_text(
            "❯ .\n\n✻ Churned for 5s"
        )

        self.assertTrue(backend._contains_claude_trust_prompt(trust))
        self.assertTrue(backend._contains_claude_auth_blocker(auth))
        self.assertTrue(backend._contains_generic_confirmation_blocker(confirmation))
        self.assertTrue(backend._contains_claude_ready_prompt(ready))
        self.assertTrue(backend._contains_runner_status_signal(status_signal))
        self.assertTrue(backend._contains_claude_ready_prompt(status_signal))


if __name__ == "__main__":
    unittest.main()
