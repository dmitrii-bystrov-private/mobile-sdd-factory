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


if __name__ == "__main__":
    unittest.main()
