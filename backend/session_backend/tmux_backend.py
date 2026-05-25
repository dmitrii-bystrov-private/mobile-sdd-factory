"""tmux-backed implementation of the session runtime abstraction."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import os
import re
import shutil
import subprocess
import time

from backend.session_backend.base import SessionBackend
from backend.session_backend.runtime_models import RuntimeOutputChunk, RuntimeRoleHandle, RuntimeSessionHandle


class TmuxSessionBackend(SessionBackend):
    """Placeholder tmux backend.

    The implementation will be added after coordinator/state contracts stabilize.
    """

    _MCP_FAILED_CLIENT_RE = re.compile(r"mcp client for [`']?([a-z0-9][a-z0-9_-]*)[`']? failed to start")
    _MCP_FAILED_LIST_RE = re.compile(r"failed:\s*([a-z0-9_, -]+)")
    _LAUNCHER_RUNNER_RE = re.compile(r"export\s+SDD_FACTORY_ROLE_RUNNER=(.+)")
    _DEFAULT_TMUX_WIDTH = 220
    _DEFAULT_TMUX_HEIGHT = 60

    def __init__(
        self,
        mode: str = "auto",
        runtime_root: Path | None = None,
        socket_root: Path | None = None,
    ) -> None:
        self.mode = mode
        self.runtime_root = runtime_root or Path.cwd() / "workdir"
        self.socket_root = socket_root or (self.runtime_root / ".tmux-sockets")
        self.tmux_width = self._read_tmux_dimension("SDD_FACTORY_TMUX_WIDTH", self._DEFAULT_TMUX_WIDTH)
        self.tmux_height = self._read_tmux_dimension("SDD_FACTORY_TMUX_HEIGHT", self._DEFAULT_TMUX_HEIGHT)
        self.sent_inputs: dict[str, list[str]] = defaultdict(list)
        self.pending_outputs: dict[str, list[str]] = defaultdict(list)
        self.last_captured_output: dict[str, str] = {}
        self.last_spawn_commands: dict[str, list[str]] = {}
        self.role_working_directories: dict[str, Path] = {}
        self.session_runtime_roots: dict[str, Path] = {}
        self.session_role_ids: dict[str, set[str]] = defaultdict(set)
        self.tmux_buffered_inputs: dict[str, list[str]] = defaultdict(list)
        self.tmux_submit_traces: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.tmux_interactive_driver_enabled: dict[str, bool] = {}
        self.tmux_launcher_runners: dict[str, str] = {}
        self.tmux_role_ready: dict[str, bool] = defaultdict(lambda: True)
        self.tmux_output_buffers: dict[str, str] = defaultdict(str)
        self.tmux_trust_prompt_handled: dict[str, bool] = defaultdict(bool)
        self.tmux_update_prompt_handled: dict[str, bool] = defaultdict(bool)
        self.tmux_selection_blocker_emitted: dict[str, bool] = defaultdict(bool)
        self.tmux_confirmation_blocker_emitted: dict[str, bool] = defaultdict(bool)
        self.tmux_generic_blocker_emitted: dict[str, bool] = defaultdict(bool)
        self.tmux_pre_ready_unknown_chunks: dict[str, int] = defaultdict(int)
        self._available = shutil.which("tmux") is not None
        self._effective_mode = self._resolve_mode(mode)

    @property
    def effective_mode(self) -> str:
        return self._effective_mode

    def _resolve_mode(self, mode: str) -> str:
        if mode == "recording":
            return "recording"
        if mode in {"auto", "tmux"}:
            if not self._available:
                raise ValueError("tmux is required for the operational runtime host")
            return "tmux"
        raise ValueError(f"Unsupported runtime backend mode: {mode}")

    def _read_tmux_dimension(self, env_name: str, default: int) -> int:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return value if value > 0 else default

    _ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    _ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\\\)")
    _ANSI_ESC_RE = re.compile(r"\x1B[@-_]")
    _RUNNER_STATUS_SIGNAL_RE = re.compile(r"✻\s+\S+\s+for\s+\d+[smh](?:\s+\d+[smh])*")
    _SNAPSHOT_SCROLLBACK_LINES = 300
    _LAUNCHER_INPUT_VISIBILITY_RETRIES = 4
    _LAUNCHER_INPUT_VISIBILITY_DELAY_SECONDS = 0.12

    def _sanitize(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "-", value)

    def _normalize_terminal_text(self, text: str) -> str:
        without_osc = self._ANSI_OSC_RE.sub(" ", text)
        without_csi = self._ANSI_CSI_RE.sub(" ", without_osc)
        without_esc = self._ANSI_ESC_RE.sub(" ", without_csi)
        without_controls = without_esc.replace("\r", " ").replace("\n", " ")
        return re.sub(r"\s+", " ", without_controls).strip().lower()

    def _task_runtime_root(self, task_key: str) -> Path:
        return self.runtime_root / task_key / "runtime"

    def _task_key_from_session_id(self, session_id: str) -> str:
        if session_id.startswith("sdd-"):
            return session_id[len("sdd-") :]
        return session_id

    def _role_workspace_path(self, session_id: str, role_window: str) -> Path:
        task_key = self._task_key_from_session_id(session_id)
        return self._task_runtime_root(task_key) / "role-workspaces" / role_window

    def _restore_tmux_role_metadata_if_needed(self, role: RuntimeRoleHandle) -> None:
        role_id = role.role_id
        if role_id in self.tmux_interactive_driver_enabled and role_id in self.role_working_directories:
            return
        role_window = role_id.split(":", 1)[1] if ":" in role_id else role_id
        workspace = self._role_workspace_path(role.session_id, role_window)
        if not workspace.exists():
            return
        self.role_working_directories.setdefault(role_id, workspace)
        self.last_captured_output.setdefault(role_id, "")
        self.session_role_ids[role.session_id].add(role_id)
        launcher_script = workspace / "launch-role.sh"
        interactive_driver_enabled = launcher_script.is_file()
        self.tmux_interactive_driver_enabled.setdefault(role_id, interactive_driver_enabled)
        if interactive_driver_enabled:
            self.tmux_launcher_runners.setdefault(role_id, self._extract_launcher_runner(launcher_script))
            # Recovered launcher-backed roles already have a live TUI window; treat them as ready
            # so routed work keeps using the file-backed launcher path after backend restarts.
            self.tmux_role_ready.setdefault(role_id, True)
            self.tmux_trust_prompt_handled.setdefault(role_id, True)
            self.tmux_update_prompt_handled.setdefault(role_id, True)
        else:
            self.tmux_role_ready.setdefault(role_id, True)

    def _socket_path(self, session_name: str) -> Path:
        socket_root = self.socket_root
        socket_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(session_name.encode("utf-8")).hexdigest()[:12]
        return socket_root / f"{digest}.sock"

    def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["tmux", "-S", str(socket_path), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def _extract_launcher_runner(self, launcher_script: Path) -> str:
        try:
            content = launcher_script.read_text()
        except OSError:
            return ""
        for line in content.splitlines():
            match = self._LAUNCHER_RUNNER_RE.match(line.strip())
            if not match:
                continue
            raw_value = match.group(1).strip()
            if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
                raw_value = raw_value[1:-1]
            return raw_value
        return ""

    def _launcher_submit_style(self, role_id: str, source: str) -> str:
        runner = self.tmux_launcher_runners.get(role_id, "").strip().lower() or "default"
        env_name = f"SDD_FACTORY_TMUX_SUBMIT_STYLE_{runner.upper()}_{source.upper()}"
        style = os.environ.get(env_name, "").strip().lower()
        if style:
            return style
        return "plain-enter-two-call"

    def _list_tmux_windows(self, socket_path: Path, session_name: str) -> list[tuple[str, str]]:
        result = self._tmux(socket_path, "list-windows", "-t", session_name, "-F", "#{window_index}\t#{window_name}")
        if result.returncode != 0:
            return []
        windows: list[tuple[str, str]] = []
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            index, name = line.split("\t", 1)
            windows.append((index.strip(), name.strip()))
        return windows

    def _kill_tmux_windows_by_name(self, socket_path: Path, session_name: str, window_name: str) -> None:
        for index, name in self._list_tmux_windows(socket_path, session_name):
            if name != window_name:
                continue
            self._tmux(socket_path, "kill-window", "-t", f"{session_name}:{index}")

    def create_task_session(self, task_key: str) -> RuntimeSessionHandle:
        session_name = f"sdd-{self._sanitize(task_key)}"
        self.session_runtime_roots[session_name] = self._task_runtime_root(task_key)
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session_name)
            result = self._tmux(
                socket_path,
                "new-session",
                "-d",
                "-x",
                str(self.tmux_width),
                "-y",
                str(self.tmux_height),
                "-s",
                session_name,
                "sh",
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to create tmux session")
        return RuntimeSessionHandle(session_id=session_name)

    def spawn_role(
        self,
        session: RuntimeSessionHandle,
        role_name: str,
        start_directory: Path | None = None,
        launch_command: list[str] | None = None,
    ) -> RuntimeRoleHandle:
        role_window = self._sanitize(role_name)
        role_id = f"{session.session_id}:{role_window}"
        role_command = list(launch_command or ["sh"])
        if start_directory is not None:
            start_directory.mkdir(parents=True, exist_ok=True)
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session.session_id)
            self._kill_tmux_windows_by_name(socket_path, session.session_id, role_window)
            args = [
                "new-window",
                "-d",
                "-t",
                session.session_id,
                "-n",
                role_window,
            ]
            if start_directory is not None:
                args.extend(["-c", str(start_directory)])
            args.extend(role_command)
            result = self._tmux(socket_path, *args)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to create tmux window")
            interactive_driver_enabled = bool(role_command) and Path(role_command[0]).name == "launch-role.sh"
            self.tmux_interactive_driver_enabled[role_id] = interactive_driver_enabled
            if interactive_driver_enabled and start_directory is not None:
                self.tmux_launcher_runners[role_id] = self._extract_launcher_runner(start_directory / "launch-role.sh")
            self.tmux_role_ready[role_id] = not interactive_driver_enabled
            self.tmux_trust_prompt_handled[role_id] = False
            self.tmux_update_prompt_handled[role_id] = False
            self.tmux_generic_blocker_emitted[role_id] = False
            self.tmux_selection_blocker_emitted[role_id] = False
            self.tmux_confirmation_blocker_emitted[role_id] = False
            self.tmux_pre_ready_unknown_chunks[role_id] = 0
            self.session_role_ids[session.session_id].add(role_id)
        self.last_spawn_commands[role_id] = role_command
        if start_directory is not None:
            self.role_working_directories[role_id] = start_directory
            self.last_captured_output.setdefault(role_id, "")
        return RuntimeRoleHandle(
            role_id=role_id,
            session_id=session.session_id,
            backend_name="tmux" if self._effective_mode == "tmux" else self._effective_mode,
        )

    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        self.sent_inputs[role.role_id].append(text)
        if self._effective_mode == "tmux":
            self._restore_tmux_role_metadata_if_needed(role)
            if self.tmux_interactive_driver_enabled.get(role.role_id, False) and not self.tmux_role_ready.get(role.role_id, True):
                self.tmux_buffered_inputs[role.role_id].append(text)
                return
            socket_path = self._socket_path(role.session_id)
            if self.tmux_interactive_driver_enabled.get(role.role_id, False):
                self.tmux_output_buffers[role.role_id] = ""
                self.tmux_selection_blocker_emitted[role.role_id] = False
                self.tmux_confirmation_blocker_emitted[role.role_id] = False
                self.tmux_generic_blocker_emitted[role.role_id] = False
                self.tmux_pre_ready_unknown_chunks[role.role_id] = 0
                self._write_tmux_launcher_input(role.role_id, socket_path, role.role_id, text, source="direct")
                return
            result = self._tmux(socket_path, "send-keys", "-t", role.role_id, text, "Enter")
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to send tmux input")

    def read_output(self, role: RuntimeRoleHandle) -> list[RuntimeOutputChunk]:
        if self._effective_mode == "recording":
            outputs = self.pending_outputs.pop(role.role_id, [])
            return [RuntimeOutputChunk(role_id=role.role_id, text=text) for text in outputs]

        self._restore_tmux_role_metadata_if_needed(role)
        socket_path = self._socket_path(role.session_id)
        result = self._tmux(socket_path, "capture-pane", "-p", "-t", role.role_id)
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").lower()
            if "can't find window" in error_text or "can't find pane" in error_text:
                return []
            raise RuntimeError(result.stderr or result.stdout or "Failed to capture tmux output")
        current = result.stdout
        previous = self.last_captured_output.get(role.role_id, "")
        self.last_captured_output[role.role_id] = current
        if current == previous:
            if (
                current
                and self.tmux_interactive_driver_enabled.get(role.role_id, False)
                and not self.tmux_role_ready.get(role.role_id, False)
            ):
                synthetic_markers = self._handle_tmux_interactive_driver_output(role.role_id, current)
                return [RuntimeOutputChunk(role_id=role.role_id, text=text) for text in synthetic_markers]
            return []
        if previous and current.startswith(previous):
            delta = current[len(previous):]
        else:
            delta = current
        if not delta:
            return []
        synthetic_markers = self._handle_tmux_interactive_driver_output(role.role_id, delta)
        chunks = [RuntimeOutputChunk(role_id=role.role_id, text=delta)]
        for marker_text in synthetic_markers:
            chunks.append(RuntimeOutputChunk(role_id=role.role_id, text=marker_text))
        return chunks

    def capture_output_snapshot(self, role: RuntimeRoleHandle) -> str:
        if self._effective_mode == "recording":
            return "".join(self.pending_outputs.get(role.role_id, []))

        self._restore_tmux_role_metadata_if_needed(role)
        socket_path = self._socket_path(role.session_id)
        result = self._tmux(
            socket_path,
            "capture-pane",
            "-p",
            "-S",
            f"-{self._SNAPSHOT_SCROLLBACK_LINES}",
            "-t",
            role.role_id,
        )
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").lower()
            if "can't find window" in error_text or "can't find pane" in error_text:
                return ""
            raise RuntimeError(result.stderr or result.stdout or "Failed to capture tmux output")
        current = result.stdout
        if current:
            before_trust = self.tmux_trust_prompt_handled.get(role.role_id, False)
            before_update = self.tmux_update_prompt_handled.get(role.role_id, False)
            self._auto_advance_snapshot_bootstrap_prompts(role.role_id, current)
            if self.tmux_interactive_driver_enabled.get(role.role_id, False):
                self._handle_tmux_interactive_driver_output(role.role_id, current)
            if (
                self.tmux_trust_prompt_handled.get(role.role_id, False) != before_trust
                or self.tmux_update_prompt_handled.get(role.role_id, False) != before_update
            ):
                time.sleep(0.12)
                retry = self._tmux(
                    socket_path,
                    "capture-pane",
                    "-p",
                    "-S",
                    f"-{self._SNAPSHOT_SCROLLBACK_LINES}",
                    "-t",
                    role.role_id,
                )
                if retry.returncode == 0:
                    return retry.stdout
        return current

    def _auto_advance_snapshot_bootstrap_prompts(self, role_id: str, text: str) -> None:
        normalized = self._normalize_terminal_text(text)
        runtime_handle = role_id
        session_id = runtime_handle.split(":", 1)[0]
        socket_path = self._socket_path(session_id)
        if (
            not self.tmux_trust_prompt_handled.get(role_id, False)
            and self._contains_workspace_trust_prompt(normalized)
        ):
            self._tmux(socket_path, "send-keys", "-t", runtime_handle, "1", "C-m")
            self.tmux_trust_prompt_handled[role_id] = True
        if (
            not self.tmux_update_prompt_handled.get(role_id, False)
            and self._contains_update_prompt(normalized)
        ):
            self._tmux(socket_path, "send-keys", "-t", runtime_handle, "2", "C-m")
            self.tmux_update_prompt_handled[role_id] = True

    def is_role_alive(self, role: RuntimeRoleHandle) -> bool:
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(role.session_id)
            result = self._tmux(socket_path, "list-panes", "-t", role.role_id)
            return result.returncode == 0
        return role.role_id in self.pending_outputs or role.role_id in self.sent_inputs or role.role_id in self.last_spawn_commands

    def stop_role(self, role: RuntimeRoleHandle) -> None:
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(role.session_id)
            self._tmux(socket_path, "kill-window", "-t", role.role_id)
            role_window = role.role_id.split(":", 1)[1] if ":" in role.role_id else role.role_id
            self._kill_tmux_windows_by_name(socket_path, role.session_id, role_window)
            self.tmux_buffered_inputs.pop(role.role_id, None)
            self.tmux_submit_traces.pop(role.role_id, None)
            self.tmux_interactive_driver_enabled.pop(role.role_id, None)
            self.tmux_launcher_runners.pop(role.role_id, None)
            self.tmux_role_ready.pop(role.role_id, None)
            self.tmux_output_buffers.pop(role.role_id, None)
            self.tmux_trust_prompt_handled.pop(role.role_id, None)
            self.tmux_update_prompt_handled.pop(role.role_id, None)
            self.tmux_selection_blocker_emitted.pop(role.role_id, None)
            self.tmux_confirmation_blocker_emitted.pop(role.role_id, None)
            self.tmux_generic_blocker_emitted.pop(role.role_id, None)
            self.tmux_pre_ready_unknown_chunks.pop(role.role_id, None)
            self.last_captured_output.pop(role.role_id, None)
            self.role_working_directories.pop(role.role_id, None)
            self.session_role_ids.get(role.session_id, set()).discard(role.role_id)

    def stop_session(self, session: RuntimeSessionHandle) -> None:
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session.session_id)
            for role_id in list(self.session_role_ids.get(session.session_id, set())):
                self.tmux_buffered_inputs.pop(role_id, None)
                self.tmux_submit_traces.pop(role_id, None)
                self.tmux_interactive_driver_enabled.pop(role_id, None)
                self.tmux_launcher_runners.pop(role_id, None)
                self.tmux_role_ready.pop(role_id, None)
                self.tmux_output_buffers.pop(role_id, None)
                self.tmux_trust_prompt_handled.pop(role_id, None)
                self.tmux_update_prompt_handled.pop(role_id, None)
                self.tmux_selection_blocker_emitted.pop(role_id, None)
                self.tmux_confirmation_blocker_emitted.pop(role_id, None)
                self.tmux_generic_blocker_emitted.pop(role_id, None)
                self.tmux_pre_ready_unknown_chunks.pop(role_id, None)
                self.last_captured_output.pop(role_id, None)
                self.role_working_directories.pop(role_id, None)
            self._tmux(socket_path, "kill-session", "-t", session.session_id)
            if socket_path.exists():
                socket_path.unlink()
            self.session_role_ids.pop(session.session_id, None)
        self.session_runtime_roots.pop(session.session_id, None)

    def get_sent_inputs(self, role_id: str) -> list[str]:
        return list(self.sent_inputs.get(role_id, []))

    def simulate_output(self, role_id: str, text: str) -> None:
        self.pending_outputs[role_id].append(text)

    def get_spawn_command(self, role_id: str) -> list[str]:
        return list(self.last_spawn_commands.get(role_id, []))

    def _handle_tmux_interactive_driver_output(self, role_id: str, text: str) -> list[str]:
        if not self.tmux_interactive_driver_enabled.get(role_id, False):
            return []

        accumulated = self.tmux_output_buffers.get(role_id, "") + text
        self.tmux_output_buffers[role_id] = accumulated[-32768:]
        synthetic_markers: list[str] = []
        blocker_detected = False
        ready_before_chunk = self.tmux_role_ready.get(role_id, False)

        normalized = self._normalize_terminal_text(accumulated)
        recent_normalized = self._normalize_terminal_text(text[-4000:])
        trust_prompt = self._contains_workspace_trust_prompt(normalized)
        update_prompt = self._contains_update_prompt(normalized)
        selection_blocker = self._contains_generic_selection_blocker(recent_normalized)
        confirmation_blocker = self._contains_generic_confirmation_blocker(recent_normalized)
        mcp_blocker_details = self._build_mcp_availability_blocker_details(normalized)

        if not self.tmux_role_ready.get(role_id, False):
            if (
                not self.tmux_trust_prompt_handled.get(role_id, False)
                and trust_prompt
            ):
                runtime_handle = role_id
                session_id = runtime_handle.split(":", 1)[0]
                socket_path = self._socket_path(session_id)
                self._tmux(socket_path, "send-keys", "-t", runtime_handle, "1", "C-m")
                self.tmux_trust_prompt_handled[role_id] = True
            if (
                not self.tmux_update_prompt_handled.get(role_id, False)
                and update_prompt
            ):
                runtime_handle = role_id
                session_id = runtime_handle.split(":", 1)[0]
                socket_path = self._socket_path(session_id)
                self._tmux(socket_path, "send-keys", "-t", runtime_handle, "2", "C-m")
                self.tmux_update_prompt_handled[role_id] = True
            if (
                self._contains_runner_ready_prompt(recent_normalized)
                or self._contains_runner_ready_prompt(normalized)
            ):
                self.tmux_role_ready[role_id] = True
                self.tmux_pre_ready_unknown_chunks[role_id] = 0
        if (
            self.tmux_role_ready.get(role_id, False)
            and not confirmation_blocker
            and not self.tmux_selection_blocker_emitted.get(role_id, False)
            and selection_blocker
        ):
            self.tmux_selection_blocker_emitted[role_id] = True
            blocker_detected = True
            synthetic_markers.append(
                'SDD_ERROR: {"summary":"interactive selection required","details":"launcher-backed role requested explicit selection input"}'
            )
        elif (
            self.tmux_role_ready.get(role_id, False)
            and not self.tmux_confirmation_blocker_emitted.get(role_id, False)
            and confirmation_blocker
        ):
            self.tmux_confirmation_blocker_emitted[role_id] = True
            blocker_detected = True
            synthetic_markers.append(
                'SDD_ERROR: {"summary":"interactive confirmation required","details":"launcher-backed role requested explicit confirmation"}'
            )
        elif (
            not ready_before_chunk
            and not self.tmux_role_ready.get(role_id, False)
            and self.tmux_buffered_inputs.get(role_id)
            and normalized
            and not trust_prompt
            and not selection_blocker
            and not self._contains_launcher_bootstrap_noise(recent_normalized)
            and not self.tmux_generic_blocker_emitted.get(role_id, False)
        ):
            self.tmux_pre_ready_unknown_chunks[role_id] += 1
            if self.tmux_pre_ready_unknown_chunks[role_id] >= 3:
                self.tmux_generic_blocker_emitted[role_id] = True
                blocker_detected = True
                if mcp_blocker_details is not None:
                    synthetic_markers.append(
                        'SDD_ERROR: {"summary":"required mcp access unavailable","details":"'
                        + mcp_blocker_details.replace('"', '\\"')
                        + '","resume_strategy":"reactivate_only"}'
                    )
                else:
                    preview = normalized[:160]
                    synthetic_markers.append(
                        'SDD_ERROR: {"summary":"interactive operator input required","details":"launcher-backed role emitted unresolved interactive output before ready: '
                        + preview.replace('"', '\\"')
                        + '"}'
                    )
        if self.tmux_role_ready.get(role_id, False) and not blocker_detected:
            runtime_handle = role_id
            session_id = runtime_handle.split(":", 1)[0]
            socket_path = self._socket_path(session_id)
            for buffered_text in self.tmux_buffered_inputs.pop(role_id, []):
                self._write_tmux_launcher_input(role_id, socket_path, runtime_handle, buffered_text, source="buffered")
        return synthetic_markers

    def _contains_workspace_trust_prompt(self, normalized_text: str) -> bool:
        return (
            (
                "quick safety check" in normalized_text
                and "trust" in normalized_text
                and "folder" in normalized_text
            )
            or (
                "do you trust the contents of this directory" in normalized_text
                and "press enter to continue" in normalized_text
            )
        )

    def _contains_update_prompt(self, normalized_text: str) -> bool:
        return (
            "update available!" in normalized_text
            and "release notes:" in normalized_text
            and "press enter to continue" in normalized_text
            and "skip" in normalized_text
        )

    def _contains_runner_ready_prompt(self, normalized_text: str) -> bool:
        return (
            "agent_ready" in normalized_text
            or self._contains_runner_status_signal(normalized_text)
            or self._contains_interactive_input_prompt(normalized_text)
        )

    def _contains_generic_selection_blocker(self, normalized_text: str) -> bool:
        return (
            "enter to select" in normalized_text
            and "to navigate" in normalized_text
            and "esc to cancel" in normalized_text
        )

    def _contains_generic_confirmation_blocker(self, normalized_text: str) -> bool:
        if "confirm tool execution" in normalized_text and "enter to confirm" in normalized_text:
            return True
        return (
            "enter to confirm" in normalized_text
            and "esc to cancel" in normalized_text
            and "trust this folder" not in normalized_text
        )

    def _contains_runner_status_signal(self, normalized_text: str) -> bool:
        return self._RUNNER_STATUS_SIGNAL_RE.search(normalized_text) is not None

    def _contains_interactive_input_prompt(self, normalized_text: str) -> bool:
        return (
            ("❯" in normalized_text or "›" in normalized_text)
            and "quick safety check" not in normalized_text
            and "do you trust the contents of this directory" not in normalized_text
            and "enter to confirm" not in normalized_text
            and "enter to select" not in normalized_text
        )

    def _contains_launcher_bootstrap_noise(self, normalized_text: str) -> bool:
        return (
            "sdd_factory_role_launcher_ready" in normalized_text
            or "sdd_factory_agent_bootstrap" in normalized_text
        )

    def _build_mcp_availability_blocker_details(self, normalized_text: str) -> str | None:
        if "mcp" not in normalized_text:
            return None
        if not any(
            marker in normalized_text
            for marker in (
                "failed to start",
                "mcp startup incomplete",
                "mcp startup failed",
                "needs auth",
                "unauthorized",
                "authentication",
                "http request failed",
                "send initialize request",
            )
        ):
            return None

        server_names: set[str] = set(self._MCP_FAILED_CLIENT_RE.findall(normalized_text))
        for match in self._MCP_FAILED_LIST_RE.findall(normalized_text):
            for item in match.split(","):
                candidate = item.strip()
                if (
                    candidate
                    and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", candidate)
                    and ("-" in candidate or candidate == "notion")
                ):
                    server_names.add(candidate)
        if not server_names:
            return None

        ordered_names = ", ".join(sorted(server_names))
        return (
            f"required MCP access is unavailable for: {ordered_names}. "
            "Restore availability first, for example by authorizing the affected MCP, enabling VPN, or fixing network access, then use Resume Session to continue the current work."
        )

    def _materialize_routed_input(self, role_id: str, text: str) -> str:
        workspace = self.role_working_directories.get(role_id)
        if workspace is None:
            return text
        routed_input_path = workspace / "ROUTED_WORK.md"
        routed_input_path.write_text(text)
        dispatch_token = self._read_launcher_dispatch_token(role_id)
        dispatch_suffix = f" Dispatch token: {dispatch_token}." if dispatch_token else ""
        return (
            "Read ROUTED_WORK.md in the current directory, read HYDRATION.json too if it exists, follow the routed instructions exactly, "
            f"and reply only through the SDD_* protocol described in AGENTS.md.{dispatch_suffix}"
        )

    def _read_launcher_dispatch_token(self, role_id: str) -> str:
        workspace = self.role_working_directories.get(role_id)
        if workspace is None:
            return ""
        hydration_path = workspace / "HYDRATION.json"
        if not hydration_path.is_file():
            return ""
        try:
            parsed = json.loads(hydration_path.read_text())
        except Exception:
            return ""
        token = parsed.get("dispatch_token")
        return str(token).strip() if token is not None else ""

    def _normalize_launcher_input_text(self, text: str) -> str:
        normalized = " ".join(text.split()).strip()
        return normalized or text.strip()

    def _capture_tmux_pane_text(self, socket_path: Path, runtime_handle: str) -> str:
        result = self._tmux(socket_path, "capture-pane", "-p", "-S", "-40", "-t", runtime_handle)
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").lower()
            if "can't find window" in error_text or "can't find pane" in error_text:
                return ""
            raise RuntimeError(result.stderr or result.stdout or "Failed to capture tmux pane")
        return result.stdout

    def _confirm_tmux_launcher_input_visible(
        self,
        socket_path: Path,
        runtime_handle: str,
        payload_text: str,
    ) -> None:
        expected = self._normalize_terminal_text(payload_text)
        if not expected:
            return
        for _ in range(self._LAUNCHER_INPUT_VISIBILITY_RETRIES):
            pane_text = self._capture_tmux_pane_text(socket_path, runtime_handle)
            normalized_pane = self._normalize_terminal_text(pane_text)
            if expected in normalized_pane:
                return
            time.sleep(self._LAUNCHER_INPUT_VISIBILITY_DELAY_SECONDS)
        raise RuntimeError("tmux launcher input was not visible in the runner window after submit")

    def _write_tmux_launcher_input(
        self,
        role_id: str,
        socket_path: Path,
        runtime_handle: str,
        text: str,
        *,
        source: str,
    ) -> None:
        payload_text = text
        if "\n" in text:
            payload_text = self._materialize_routed_input(role_id, text)
        payload_text = self._normalize_launcher_input_text(payload_text)
        submit_style = self._launcher_submit_style(role_id, source)
        submit_key = "Enter"
        self.tmux_submit_traces[role_id].append(
            {
                "source": source,
                "original_text": text,
                "payload_text": payload_text,
                "submit_key": submit_key,
                "submit_style": submit_style,
                "runner": self.tmux_launcher_runners.get(role_id, ""),
            }
        )
        if submit_style == "plain-enter-two-call":
            result = self._tmux(socket_path, "send-keys", "-t", runtime_handle, payload_text, "")
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to send tmux launcher input")
            time.sleep(0.25)
            result = self._tmux(socket_path, "send-keys", "-t", runtime_handle, "", "Enter")
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to submit tmux launcher input")
            self._confirm_tmux_launcher_input_visible(socket_path, runtime_handle, payload_text)
            return

        result = self._tmux(socket_path, "send-keys", "-t", runtime_handle, "-l", payload_text)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "Failed to send tmux launcher input")
        time.sleep(0.25)
        result = self._tmux(socket_path, "send-keys", "-t", runtime_handle, submit_key)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "Failed to submit tmux launcher input")
        self._confirm_tmux_launcher_input_visible(socket_path, runtime_handle, payload_text)

    def get_tmux_submit_traces(self, role_id: str) -> list[dict[str, str]]:
        return list(self.tmux_submit_traces.get(role_id, []))

    def get_tmux_visibility(self, session_id: str, role_id: str | None = None) -> dict[str, str] | None:
        if self._effective_mode != "tmux":
            return None
        socket_path = self._socket_path(session_id)
        payload: dict[str, str] = {
            "tmux_socket_path": str(socket_path),
            "tmux_attach_command": f"tmux -S {str(socket_path)!r} attach -t {session_id!r}",
        }
        if role_id is not None:
            payload["tmux_role_attach_command"] = (
                f"tmux -S {str(socket_path)!r} attach -t {session_id!r} \\; select-window -t {role_id!r}"
            )
            payload["tmux_role_capture_command"] = (
                f"tmux -S {str(socket_path)!r} capture-pane -p -S - -t {role_id!r}"
            )
        return payload
