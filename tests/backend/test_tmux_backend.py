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

    def test_tmux_capture_delta_uses_overlap_when_scrollback_window_shifts(self) -> None:
        previous = "line 1\nSDD_ERROR: {\"summary\":\"needs operator\"}\nline 3\n"
        current = "line 3\nline 4\n"

        delta = TmuxSessionBackend._tmux_capture_delta(previous=previous, current=current)

        self.assertEqual("line 4\n", delta)

    def test_tmux_mode_read_output_captures_scrollback_window(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(
                        ["tmux", *args],
                        0,
                        "older scrollback\nSDD_ERROR: {\"summary\":\"needs operator\",\"needs_operator_input\":true}\n",
                        "",
                    )
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50011:implementer",
            session_id="sdd-IOS-50011",
            backend_name="tmux",
        )

        chunks = backend.read_output(role)

        self.assertEqual(1, len(chunks))
        self.assertIn("SDD_ERROR", chunks[0].text)
        self.assertIn(
            ("capture-pane", "-p", "-S", "-2000", "-t", role.role_id),
            backend.calls,
        )

    def test_terminal_idle_signature_detects_final_duration_followed_by_prompt(self) -> None:
        backend = TmuxSessionBackend(mode="recording")

        claude_signature = backend._extract_terminal_idle_signature(
            "⏺ SDD_OUTPUT: {\"output_type\":\"completed\"}\n"
            "\n"
            "✻ Churned for 5m 3s\n"
            "\n"
            "──────────────────── doc-harvest-worker:IOS-13093 ──\n"
            "❯ show me what changed in the last commit\n"
            "────────────────────────────────────────────────────\n"
            "  [Sonnet 4.6] ████████░░ 83% | $3.16 | 5905m 0s new task? /clear to save 165.6k tokens\n"
            "  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents /rc active\n"
        )
        codex_signature = backend._extract_terminal_idle_signature(
            "• SDD_OUTPUT: {\"output_type\":\"passed\"}\n"
            "\n"
            "─ Worked for 1m 26s ───────────────────────────────────────────────────────────────\n"
            "\n"
            "\n"
            "› Run /review on my current changes\n"
            "\n"
            "  gpt-5.4 medium · ~/Projects/Finom/workdir/IOS-13093/runtime/role-workspaces/documentation-reviewer · Context 58% used · 5h 85% left · weekly 52% left\n"
        )

        self.assertIn("churned for 5m 3s", claude_signature or "")
        self.assertIn("show me what changed", claude_signature or "")
        self.assertIn("worked for 1m 26s", codex_signature or "")
        self.assertIn("run /review", codex_signature or "")
        self.assertEqual(
            "✻ baked for 5s\n❯",
            backend._extract_terminal_idle_signature("✻ Baked for 5s\n\n❯"),
        )

    def test_terminal_idle_signature_detects_final_duration_before_claude_feedback_prompt(self) -> None:
        backend = TmuxSessionBackend(mode="recording")

        signature = backend._extract_terminal_idle_signature(
            "Requirements-review correction applied and submitted via the SDD protocol.\n"
            "\n"
            "✻ Churned for 4m 3s\n"
            "\n"
            "● How is Claude doing this session? (optional)\n"
            "  1: Bad    2: Fine   3: Good   0: Dismiss\n"
            "\n"
            "──────────────────────── implementer:IOS-13327 ──\n"
            "❯\n"
            "──────────────────────────────────────────────────\n"
            "  [Opus 4.8] ██████░░░░ 62% | $95.83 | 7550m 50s\n"
            "  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents\n"
        )

        self.assertIn("churned for 4m 3s", signature or "")
        self.assertIn("❯", signature or "")

    def test_terminal_idle_signature_ignores_active_working_counter(self) -> None:
        backend = TmuxSessionBackend(mode="recording")

        signature = backend._extract_terminal_idle_signature(
            "› Read ROUTED_WORK.md\n"
            "\n"
            "• Working (5m 21s • esc to interrupt)\n"
            "\n"
            "  gpt-5.4 medium · ~/repo · Context 29% used\n"
        )

        self.assertIsNone(signature)

    def test_terminal_idle_signature_detects_model_capacity_tail(self) -> None:
        backend = TmuxSessionBackend(mode="recording")

        signature = backend._extract_terminal_idle_signature(
            "› Read ROUTED_WORK.md in the current directory\n"
            "\n"
            "⚠ Selected model is at capacity. Please try a different model.\n"
            "\n"
            "\n"
            "› Find and fix a bug in @filename\n"
            "\n"
            "  gpt-5.4 medium · ~/repo · Context 76% used · weekly 88% left\n"
        )

        self.assertIn("selected model is at capacity", signature or "")
        self.assertIn("find and fix a bug", signature or "")

    def test_terminal_idle_signature_rejects_counter_separated_from_prompt_by_work_output(self) -> None:
        backend = TmuxSessionBackend(mode="recording")

        signature = backend._extract_terminal_idle_signature(
            "✻ Cogitated for 45s\n"
            "\n"
            "❯ Read ROUTED_WORK.md in the current directory, read HYDRATION.json too if it exists\n"
            "\n"
            "⏺ The implementation is complete. Submitting:\n"
            "\n"
            "⏺ Bash(bash \"$SDD_FACTORY_REPO_ROOT/scripts/write-result.sh\" --work-item-id 2485)\n"
            "  ⎿  (No output)\n"
            "\n"
            "❯\n"
        )

        self.assertIsNone(signature)

    def test_tmux_mode_pokes_stalled_role_after_stable_terminal_idle_tail(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:2] == ("list-panes", "-t"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, "0: [220x60]\n", "")
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        backend.tmux_stall_poke_threshold_seconds = 30.0
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50010:implementer",
            session_id="sdd-IOS-50010",
            backend_name="tmux",
        )
        snapshot = "Done.\n✻ Crunched for 1m 38s\n\n❯ <dispatch token to continue>\n"

        self.assertIsNone(backend.maybe_poke_stalled_role(role, snapshot=snapshot))
        backend.tmux_activity_updated_at[role.role_id] = time.monotonic() - 31.0
        result = backend.maybe_poke_stalled_role(
            role,
            snapshot="Done.\n✻ Crunched for 1m 38s\n\n❯ <dispatch token to continue>\n",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(".", result["poke_text"])
        self.assertIn(("send-keys", "-t", role.role_id, ".", "Enter"), backend.calls)

    def test_tmux_mode_sets_explicit_session_size_with_env_override(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if len(args) >= 3 and args[0] == "send-keys" and args[1] == "-t":
                    self.pane_text += " first routed work"
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

    def test_tmux_mode_clears_duplicate_named_windows_before_spawning_role(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:4] == ("list-windows", "-t", "sdd-IOS-50002DUP", "-F"):
                    return subprocess.CompletedProcess(
                        ["tmux", *args],
                        0,
                        "0\tbash\n1\timplementer\n2\timplementer\n",
                        "",
                    )
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        session = backend.create_task_session("IOS-50002DUP")

        backend.spawn_role(session, "implementer")

        self.assertIn(
            ("kill-window", "-t", "sdd-IOS-50002DUP:1"),
            backend.calls,
        )
        self.assertIn(
            ("kill-window", "-t", "sdd-IOS-50002DUP:2"),
            backend.calls,
        )
        self.assertIn(
            ("new-window", "-d", "-t", "sdd-IOS-50002DUP", "-n", "implementer", "sh"),
            backend.calls,
        )

    def test_tmux_launcher_prompt_echo_does_not_resubmit_input(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4 and args[3]:
                    self.pane_text += f" {args[3]}"
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

        submit_calls = [call for call in backend.calls if call[-1] == "Enter"]
        self.assertEqual([("send-keys", "-t", role.role_id, "", "Enter")], submit_calls)

    def test_tmux_launcher_normalizes_direct_input_before_submit(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4 and args[3]:
                    self.pane_text += f" {args[3]}"
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:requirements-clarifier-worker",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_role_ready[role.role_id] = True

        backend.send_input(role, " \n  Operator answer:   full repo-wide cleanup. \n ")

        submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
        self.assertEqual("Operator answer: full repo-wide cleanup.", submit_trace["payload_text"])
        self.assertEqual("Enter", submit_trace["submit_key"])
        self.assertEqual("plain-enter-two-call", submit_trace["submit_style"])
        self.assertIn(
            ("send-keys", "-t", role.role_id, "Operator answer: full repo-wide cleanup.", ""),
            backend.calls,
        )
        self.assertIn(
            ("send-keys", "-t", role.role_id, "", "Enter"),
            backend.calls,
        )

    def test_tmux_launcher_records_unconfirmed_when_input_is_not_visible_in_pane(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, "", "")
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:verification-coordinator",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_role_ready[role.role_id] = True

        backend.send_input(role, "Run deterministic verification for IOS-50009.")

        submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
        self.assertEqual("submitted_unconfirmed", submit_trace["delivery_state"])

    def test_tmux_launcher_materialized_trigger_includes_dispatch_token_from_hydration(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self, runtime_root: Path) -> None:
                super().__init__(mode="tmux", runtime_root=runtime_root)
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4 and args[3]:
                    self.pane_text += f" {args[3]}"
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            workspace = runtime_root / "IOS-50009TOKEN" / "runtime" / "role-workspaces" / "implementer"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "HYDRATION.json").write_text('{"dispatch_token":"hv7-wi123"}')

            backend = FakeTmuxBackend(runtime_root)
            role = RuntimeRoleHandle(
                role_id="sdd-IOS-50009TOKEN:implementer",
                session_id="sdd-IOS-50009TOKEN",
                backend_name="tmux",
            )
            backend.tmux_interactive_driver_enabled[role.role_id] = True
            backend.tmux_role_ready[role.role_id] = True
            backend.role_working_directories[role.role_id] = workspace

            backend.send_input(role, "line 1\nline 2")

            submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
            self.assertIn("Dispatch token: hv7-wi123.", submit_trace["payload_text"])

    def test_tmux_launcher_can_probe_plain_enter_submit_for_claude_direct_input(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4 and args[3]:
                    self.pane_text += f" {args[3]}"
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:requirements-clarifier-worker",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_launcher_runners[role.role_id] = "claude"
        backend.tmux_role_ready[role.role_id] = True

        previous = os.environ.get("SDD_FACTORY_TMUX_SUBMIT_STYLE_CLAUDE_DIRECT")
        os.environ["SDD_FACTORY_TMUX_SUBMIT_STYLE_CLAUDE_DIRECT"] = "plain-enter-two-call"
        try:
            backend.send_input(role, "Operator answer: full repo-wide cleanup.")
        finally:
            if previous is None:
                os.environ.pop("SDD_FACTORY_TMUX_SUBMIT_STYLE_CLAUDE_DIRECT", None)
            else:
                os.environ["SDD_FACTORY_TMUX_SUBMIT_STYLE_CLAUDE_DIRECT"] = previous

        submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
        self.assertEqual("claude", submit_trace["runner"])
        self.assertEqual("plain-enter-two-call", submit_trace["submit_style"])
        self.assertEqual(
            [
                ("send-keys", "-t", role.role_id, "Operator answer: full repo-wide cleanup.", ""),
                ("send-keys", "-t", role.role_id, "", "Enter"),
            ],
            backend.calls[:2],
        )
        self.assertIn(("capture-pane", "-p", "-S", "-40", "-t", role.role_id), backend.calls)

    def test_tmux_launcher_can_probe_plain_enter_submit_for_codex_direct_input(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4 and args[3]:
                    self.pane_text += f" {args[3]}"
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:requirements-clarifier-worker",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_launcher_runners[role.role_id] = "codex"
        backend.tmux_role_ready[role.role_id] = True

        previous = os.environ.get("SDD_FACTORY_TMUX_SUBMIT_STYLE_CODEX_DIRECT")
        os.environ["SDD_FACTORY_TMUX_SUBMIT_STYLE_CODEX_DIRECT"] = "plain-enter-two-call"
        try:
            backend.send_input(role, "Operator answer: full repo-wide cleanup.")
        finally:
            if previous is None:
                os.environ.pop("SDD_FACTORY_TMUX_SUBMIT_STYLE_CODEX_DIRECT", None)
            else:
                os.environ["SDD_FACTORY_TMUX_SUBMIT_STYLE_CODEX_DIRECT"] = previous

        submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
        self.assertEqual("codex", submit_trace["runner"])
        self.assertEqual("plain-enter-two-call", submit_trace["submit_style"])
        self.assertEqual(
            [
                ("send-keys", "-t", role.role_id, "Operator answer: full repo-wide cleanup.", ""),
                ("send-keys", "-t", role.role_id, "", "Enter"),
            ],
            backend.calls[:2],
        )
        self.assertIn(("capture-pane", "-p", "-S", "-40", "-t", role.role_id), backend.calls)

    def test_tmux_launcher_visibility_miss_is_nonfatal_after_successful_send(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, "runner already consumed input", "")
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:requirements-reviewer",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_role_ready[role.role_id] = True

        backend.send_input(role, "Review the routed work.")

        submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
        self.assertEqual("submitted_unconfirmed", submit_trace["delivery_state"])
        self.assertEqual(
            [
                ("send-keys", "-t", role.role_id, "Review the routed work.", ""),
                ("send-keys", "-t", role.role_id, "", "Enter"),
            ],
            backend.calls[:2],
        )

    def test_tmux_launcher_retries_submit_when_pane_stays_idle_after_first_enter(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []
                self.enter_count = 0
                self.pane_text = "› Summarize recent commits\n\ngpt-5.5 medium · ~/repo"

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4:
                    if args[3]:
                        self.pane_text = f"{self.pane_text}\n{args[3]}"
                    elif args[-1] == "Enter":
                        self.enter_count += 1
                        if self.enter_count >= 2:
                            self.pane_text = "◦ Working (1s • esc to interrupt)"
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50009:verification-coordinator",
            session_id="sdd-IOS-50009",
            backend_name="tmux",
        )
        backend.tmux_interactive_driver_enabled[role.role_id] = True
        backend.tmux_launcher_runners[role.role_id] = "codex"
        backend.tmux_role_ready[role.role_id] = True

        backend.send_input(role, "Run deterministic verification for IOS-50009.")

        submit_calls = [
            call
            for call in backend.calls
            if call[:3] == ("send-keys", "-t", role.role_id) and call[-1] == "Enter"
        ]
        self.assertEqual(
            [
                ("send-keys", "-t", role.role_id, "", "Enter"),
                ("send-keys", "-t", role.role_id, "", "Enter"),
            ],
            submit_calls,
        )

    def test_tmux_restores_launcher_metadata_for_existing_role_after_backend_restart(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self, runtime_root: Path) -> None:
                super().__init__(mode="tmux", runtime_root=runtime_root)
                self.calls: list[tuple[str, ...]] = []
                self.pane_text = ""

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:3] == ("capture-pane", "-p", "-S"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, self.pane_text, "")
                if args[:3] == ("send-keys", "-t", role.role_id) and len(args) >= 4 and args[3]:
                    self.pane_text += f" {args[3]}"
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            workspace = (
                runtime_root
                / "IOS-50009RECOVER"
                / "runtime"
                / "role-workspaces"
                / "implementer"
            )
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "launch-role.sh").write_text(
                "#!/usr/bin/env bash\nexport SDD_FACTORY_ROLE_RUNNER='claude'\n"
            )

            backend = FakeTmuxBackend(runtime_root)
            role = RuntimeRoleHandle(
                role_id="sdd-IOS-50009RECOVER:implementer",
                session_id="sdd-IOS-50009RECOVER",
                backend_name="tmux",
            )

            backend.send_input(
                role,
                "Read AGENTS.md first.\n\nCurrent routed work:\nImplement the assigned change.",
            )

            submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]
            self.assertEqual(
                "Read ROUTED_WORK.md in the current directory, read HYDRATION.json too if it exists, follow the routed instructions exactly, and reply only through the SDD_* protocol described in AGENTS.md.",
                submit_trace["payload_text"],
            )
            self.assertEqual("claude", submit_trace["runner"])
            self.assertTrue((workspace / "ROUTED_WORK.md").is_file())
            self.assertIn(
                ("send-keys", "-t", role.role_id, submit_trace["payload_text"], ""),
                backend.calls,
            )
        self.assertIn(
            ("send-keys", "-t", role.role_id, "", "Enter"),
            backend.calls,
        )
        self.assertIn(("capture-pane", "-p", "-S", "-40", "-t", role.role_id), backend.calls)

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

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_mode_materializes_multiline_buffered_work_before_launcher_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            backend = TmuxSessionBackend(
                mode="tmux",
                runtime_root=runtime_root,
            )
            session = backend.create_task_session("IOS-50008ROUTEDBUFFER")
            fixture = (
                Path(__file__).resolve().parent
                / "fixtures"
                / "interactive_unknown_pre_ready_fixture.py"
            )
            role_workspace = (
                runtime_root
                / "IOS-50008ROUTEDBUFFER"
                / "runtime"
                / "role-workspaces"
                / "acceptance-criteria-worker"
            )
            role_workspace.mkdir(parents=True, exist_ok=True)
            launcher_script = role_workspace / "launch-role.sh"
            launcher_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        "export SDD_FACTORY_ROLE_RUNNER='codex'",
                        f"exec python3 -u {fixture}",
                        "",
                    ]
                )
            )
            launcher_script.chmod(0o755)
            role = backend.spawn_role(
                session,
                "acceptance-criteria-worker",
                start_directory=role_workspace,
                launch_command=[str(launcher_script)],
            )

            routed_prompt = "Read AGENTS.md once.\n\nCurrent routed work:\nPrepare acceptance criteria."
            backend.send_input(role, routed_prompt)

            routed_path = role_workspace / "ROUTED_WORK.md"
            submit_trace = backend.get_tmux_submit_traces(role.role_id)[-1]

            self.assertTrue(routed_path.is_file())
            self.assertEqual(routed_prompt, routed_path.read_text())
            self.assertEqual("buffered_pre_ready", submit_trace["delivery_state"])
            self.assertEqual("buffered_pre_ready", submit_trace["source"])
            self.assertEqual("codex", submit_trace["runner"])
            self.assertEqual([submit_trace["payload_text"]], backend.tmux_buffered_inputs[role.role_id])
            self.assertIn("Read ROUTED_WORK.md", submit_trace["payload_text"])

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
        self.assertTrue(backend._contains_runner_working_signal("◦ working (1s • esc to interrupt)"))
        self.assertTrue(backend._contains_interactive_input_prompt(prompt_ready))
        self.assertTrue(backend._contains_runner_ready_prompt(prompt_ready))
        self.assertTrue(backend._contains_interactive_input_prompt(codex_prompt_ready))
        self.assertTrue(backend._contains_runner_ready_prompt(codex_prompt_ready))
        self.assertFalse(backend._contains_interactive_input_prompt(trust))
        self.assertFalse(backend._contains_interactive_input_prompt(selection))
        self.assertFalse(backend._contains_interactive_input_prompt(confirmation))
        self.assertTrue(
            backend._contains_model_capacity_blocker(
                backend._normalize_terminal_text(
                    "⚠ Selected model is at capacity. Please try a different model."
                )
            )
        )

    def test_tmux_mode_pokes_model_capacity_tail_after_threshold(self) -> None:
        class FakeTmuxBackend(TmuxSessionBackend):
            def __init__(self) -> None:
                super().__init__(mode="tmux")
                self.calls: list[tuple[str, ...]] = []

            def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
                self.calls.append(args)
                if args[:2] == ("list-panes", "-t"):
                    return subprocess.CompletedProcess(["tmux", *args], 0, "0: [220x60]\n", "")
                return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

        backend = FakeTmuxBackend()
        backend.tmux_stall_poke_threshold_seconds = 30.0
        role = RuntimeRoleHandle(
            role_id="sdd-IOS-50012:convention-reviewer",
            session_id="sdd-IOS-50012",
            backend_name="tmux",
        )
        snapshot = (
            "› Read ROUTED_WORK.md in the current directory\n"
            "\n"
            "⚠ Selected model is at capacity. Please try a different model.\n"
            "\n"
            "› Find and fix a bug in @filename\n"
            "\n"
            "  gpt-5.4 medium · ~/repo · Context 76% used · weekly 88% left\n"
        )

        self.assertIsNone(backend.maybe_poke_stalled_role(role, snapshot=snapshot))
        backend.tmux_activity_updated_at[role.role_id] = time.monotonic() - 31.0
        result = backend.maybe_poke_stalled_role(role, snapshot=snapshot)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(".", result["poke_text"])
        self.assertIn(("send-keys", "-t", role.role_id, ".", "Enter"), backend.calls)

    def test_interactive_driver_does_not_escalate_model_capacity_blocker(self) -> None:
        backend = TmuxSessionBackend(mode="recording")
        role_id = "sdd-IOS-50012:convention-reviewer"
        backend.tmux_interactive_driver_enabled[role_id] = True
        backend.tmux_role_ready[role_id] = True

        markers = backend._handle_tmux_interactive_driver_output(
            role_id,
            "› Read ROUTED_WORK.md\n"
            "\n"
            "⚠ Selected model is at capacity. Please try a different model.\n",
        )

        self.assertEqual([], markers)

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
