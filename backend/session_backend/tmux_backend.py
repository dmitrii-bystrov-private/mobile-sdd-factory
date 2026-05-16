"""tmux-backed implementation of the session runtime abstraction."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import os
import pty
import re
import shutil
import subprocess

from backend.session_backend.base import SessionBackend
from backend.session_backend.runtime_models import RuntimeOutputChunk, RuntimeRoleHandle, RuntimeSessionHandle


class TmuxSessionBackend(SessionBackend):
    """Placeholder tmux backend.

    The implementation will be added after coordinator/state contracts stabilize.
    """

    def __init__(self, mode: str = "auto", runtime_root: Path | None = None) -> None:
        self.mode = mode
        self.runtime_root = runtime_root or Path.cwd() / "workdir"
        self.sent_inputs: dict[str, list[str]] = defaultdict(list)
        self.pending_outputs: dict[str, list[str]] = defaultdict(list)
        self.last_captured_output: dict[str, str] = {}
        self.last_spawn_commands: dict[str, list[str]] = {}
        self.session_runtime_roots: dict[str, Path] = {}
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.pty_master_fds: dict[str, int] = {}
        self.session_role_ids: dict[str, set[str]] = defaultdict(set)
        self.pty_buffered_inputs: dict[str, list[str]] = defaultdict(list)
        self.pty_interactive_driver_enabled: dict[str, bool] = {}
        self.pty_role_ready: dict[str, bool] = defaultdict(lambda: True)
        self.pty_output_buffers: dict[str, str] = defaultdict(str)
        self.pty_trust_prompt_handled: dict[str, bool] = defaultdict(bool)
        self.pty_auth_blocker_emitted: dict[str, bool] = defaultdict(bool)
        self.pty_confirmation_blocker_emitted: dict[str, bool] = defaultdict(bool)
        self.pty_generic_blocker_emitted: dict[str, bool] = defaultdict(bool)
        self.pty_pre_ready_unknown_chunks: dict[str, int] = defaultdict(int)
        self._available = shutil.which("tmux") is not None
        self._effective_mode = self._resolve_mode(mode)

    @property
    def effective_mode(self) -> str:
        return self._effective_mode

    def _resolve_mode(self, mode: str) -> str:
        if mode == "recording":
            return "recording"
        if mode == "process":
            return "process"
        if mode == "pty":
            return "pty"
        if mode == "tmux":
            return "tmux"
        return "tmux" if self._available else "process"

    _ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    _ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\\\)")
    _ANSI_ESC_RE = re.compile(r"\x1B[@-_]")

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

    def _socket_path(self, session_name: str) -> Path:
        runtime_root = self.session_runtime_roots.get(session_name, self.runtime_root)
        runtime_root.mkdir(parents=True, exist_ok=True)
        return runtime_root / f"{session_name}.sock"

    def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["tmux", "-S", str(socket_path), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def create_task_session(self, task_key: str) -> RuntimeSessionHandle:
        session_name = f"sdd-{self._sanitize(task_key)}"
        self.session_runtime_roots[session_name] = self._task_runtime_root(task_key)
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session_name)
            result = self._tmux(socket_path, "new-session", "-d", "-s", session_name, "sh")
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
        elif self._effective_mode == "process":
            process = subprocess.Popen(
                role_command,
                cwd=start_directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if process.stdout is None or process.stdin is None:
                raise RuntimeError("Failed to start process runtime with pipes")
            os.set_blocking(process.stdout.fileno(), False)
            self.processes[role_id] = process
            self.session_role_ids[session.session_id].add(role_id)
        elif self._effective_mode == "pty":
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                role_command,
                cwd=start_directory,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            os.set_blocking(master_fd, False)
            self.processes[role_id] = process
            self.pty_master_fds[role_id] = master_fd
            self.session_role_ids[session.session_id].add(role_id)
            interactive_driver_enabled = bool(role_command) and Path(role_command[0]).name == "launch-role.sh"
            self.pty_interactive_driver_enabled[role_id] = interactive_driver_enabled
            self.pty_role_ready[role_id] = not interactive_driver_enabled
            self.pty_trust_prompt_handled[role_id] = False
            self.pty_generic_blocker_emitted[role_id] = False
            self.pty_pre_ready_unknown_chunks[role_id] = 0
        self.last_spawn_commands[role_id] = role_command
        if start_directory is not None:
            self.last_captured_output.setdefault(role_id, "")
        return RuntimeRoleHandle(
            role_id=role_id,
            session_id=session.session_id,
            backend_name="tmux" if self._effective_mode == "tmux" else self._effective_mode,
        )

    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        self.sent_inputs[role.role_id].append(text)
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(role.session_id)
            result = self._tmux(socket_path, "send-keys", "-t", role.role_id, text, "Enter")
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to send tmux input")
        elif self._effective_mode == "process":
            process = self.processes.get(role.role_id)
            if process is None or process.stdin is None:
                raise RuntimeError(f"Unknown process role runtime: {role.role_id}")
            process.stdin.write((text + "\n").encode())
            process.stdin.flush()
        elif self._effective_mode == "pty":
            master_fd = self.pty_master_fds.get(role.role_id)
            if master_fd is None:
                raise RuntimeError(f"Unknown PTY role runtime: {role.role_id}")
            if self.pty_interactive_driver_enabled.get(role.role_id, False) and not self.pty_role_ready.get(role.role_id, True):
                self.pty_buffered_inputs[role.role_id].append(text)
                return
            if self.pty_interactive_driver_enabled.get(role.role_id, False):
                self.pty_output_buffers[role.role_id] = ""
                self.pty_auth_blocker_emitted[role.role_id] = False
                self.pty_confirmation_blocker_emitted[role.role_id] = False
                self.pty_generic_blocker_emitted[role.role_id] = False
                self.pty_pre_ready_unknown_chunks[role.role_id] = 0
            os.write(master_fd, (text + "\n").encode())

    def read_output(self, role: RuntimeRoleHandle) -> list[RuntimeOutputChunk]:
        if self._effective_mode == "recording":
            outputs = self.pending_outputs.pop(role.role_id, [])
            return [RuntimeOutputChunk(role_id=role.role_id, text=text) for text in outputs]
        if self._effective_mode == "process":
            process = self.processes.get(role.role_id)
            if process is None or process.stdout is None:
                return []
            chunks: list[RuntimeOutputChunk] = []
            while True:
                try:
                    data = os.read(process.stdout.fileno(), 65536)
                except BlockingIOError:
                    break
                if not data:
                    break
                text = data.decode(errors="replace")
                if text:
                    chunks.append(RuntimeOutputChunk(role_id=role.role_id, text=text))
            return chunks
        if self._effective_mode == "pty":
            master_fd = self.pty_master_fds.get(role.role_id)
            if master_fd is None:
                return []
            chunks: list[RuntimeOutputChunk] = []
            while True:
                try:
                    data = os.read(master_fd, 65536)
                except BlockingIOError:
                    break
                except OSError:
                    break
                if not data:
                    break
                text = data.decode(errors="replace")
                if text:
                    synthetic_markers = self._handle_pty_interactive_driver_output(role.role_id, text)
                    chunks.append(RuntimeOutputChunk(role_id=role.role_id, text=text))
                    for marker_text in synthetic_markers:
                        chunks.append(RuntimeOutputChunk(role_id=role.role_id, text=marker_text))
            return chunks

        socket_path = self._socket_path(role.session_id)
        result = self._tmux(socket_path, "capture-pane", "-p", "-t", role.role_id)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "Failed to capture tmux output")
        current = result.stdout
        previous = self.last_captured_output.get(role.role_id, "")
        self.last_captured_output[role.role_id] = current
        if current == previous:
            return []
        if previous and current.startswith(previous):
            delta = current[len(previous):]
        else:
            delta = current
        if not delta:
            return []
        return [RuntimeOutputChunk(role_id=role.role_id, text=delta)]

    def stop_role(self, role: RuntimeRoleHandle) -> None:
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(role.session_id)
            self._tmux(socket_path, "kill-window", "-t", role.role_id)
        elif self._effective_mode == "process":
            process = self.processes.pop(role.role_id, None)
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
            self.session_role_ids.get(role.session_id, set()).discard(role.role_id)
        elif self._effective_mode == "pty":
            process = self.processes.pop(role.role_id, None)
            master_fd = self.pty_master_fds.pop(role.role_id, None)
            self.pty_buffered_inputs.pop(role.role_id, None)
            self.pty_interactive_driver_enabled.pop(role.role_id, None)
            self.pty_role_ready.pop(role.role_id, None)
            self.pty_output_buffers.pop(role.role_id, None)
            self.pty_trust_prompt_handled.pop(role.role_id, None)
            self.pty_auth_blocker_emitted.pop(role.role_id, None)
            self.pty_confirmation_blocker_emitted.pop(role.role_id, None)
            self.pty_generic_blocker_emitted.pop(role.role_id, None)
            self.pty_pre_ready_unknown_chunks.pop(role.role_id, None)
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            if master_fd is not None:
                os.close(master_fd)
            self.session_role_ids.get(role.session_id, set()).discard(role.role_id)

    def stop_session(self, session: RuntimeSessionHandle) -> None:
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session.session_id)
            self._tmux(socket_path, "kill-session", "-t", session.session_id)
            if socket_path.exists():
                socket_path.unlink()
        elif self._effective_mode == "process":
            for role_id in list(self.session_role_ids.get(session.session_id, set())):
                process = self.processes.pop(role_id, None)
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    if process.stdin is not None:
                        process.stdin.close()
                    if process.stdout is not None:
                        process.stdout.close()
            self.session_role_ids.pop(session.session_id, None)
        elif self._effective_mode == "pty":
            for role_id in list(self.session_role_ids.get(session.session_id, set())):
                process = self.processes.pop(role_id, None)
                master_fd = self.pty_master_fds.pop(role_id, None)
                self.pty_buffered_inputs.pop(role_id, None)
                self.pty_interactive_driver_enabled.pop(role_id, None)
                self.pty_role_ready.pop(role_id, None)
                self.pty_output_buffers.pop(role_id, None)
                self.pty_trust_prompt_handled.pop(role_id, None)
                self.pty_auth_blocker_emitted.pop(role_id, None)
                self.pty_confirmation_blocker_emitted.pop(role_id, None)
                self.pty_generic_blocker_emitted.pop(role_id, None)
                self.pty_pre_ready_unknown_chunks.pop(role_id, None)
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                if master_fd is not None:
                    os.close(master_fd)
            self.session_role_ids.pop(session.session_id, None)
        self.session_runtime_roots.pop(session.session_id, None)

    def get_sent_inputs(self, role_id: str) -> list[str]:
        return list(self.sent_inputs.get(role_id, []))

    def simulate_output(self, role_id: str, text: str) -> None:
        self.pending_outputs[role_id].append(text)

    def get_spawn_command(self, role_id: str) -> list[str]:
        return list(self.last_spawn_commands.get(role_id, []))

    def _handle_pty_interactive_driver_output(self, role_id: str, text: str) -> list[str]:
        if not self.pty_interactive_driver_enabled.get(role_id, False):
            return []

        accumulated = self.pty_output_buffers.get(role_id, "") + text
        self.pty_output_buffers[role_id] = accumulated[-32768:]
        synthetic_markers: list[str] = []
        blocker_detected = False
        ready_before_chunk = self.pty_role_ready.get(role_id, False)

        normalized = self._normalize_terminal_text(accumulated)
        trust_prompt = self._contains_claude_trust_prompt(normalized)
        auth_blocker = self._contains_claude_auth_blocker(normalized)
        confirmation_blocker = self._contains_generic_confirmation_blocker(normalized)

        if not self.pty_role_ready.get(role_id, False):
            if (
                not self.pty_trust_prompt_handled.get(role_id, False)
                and trust_prompt
            ):
                master_fd = self.pty_master_fds.get(role_id)
                if master_fd is not None:
                    os.write(master_fd, b"1\n")
                    self.pty_trust_prompt_handled[role_id] = True
            if self._contains_claude_ready_prompt(normalized):
                self.pty_role_ready[role_id] = True
                self.pty_pre_ready_unknown_chunks[role_id] = 0
        if (
            not self.pty_auth_blocker_emitted.get(role_id, False)
            and auth_blocker
        ):
            self.pty_auth_blocker_emitted[role_id] = True
            blocker_detected = True
            synthetic_markers.append(
                'SDD_ERROR: {"summary":"interactive auth required","details":"launcher-backed role requested connector authentication"}'
            )
        elif (
            self.pty_role_ready.get(role_id, False)
            and not self.pty_confirmation_blocker_emitted.get(role_id, False)
            and confirmation_blocker
        ):
            self.pty_confirmation_blocker_emitted[role_id] = True
            blocker_detected = True
            synthetic_markers.append(
                'SDD_ERROR: {"summary":"interactive confirmation required","details":"launcher-backed role requested explicit confirmation"}'
            )
        elif (
            not ready_before_chunk
            and not self.pty_role_ready.get(role_id, False)
            and self.pty_buffered_inputs.get(role_id)
            and normalized
            and not trust_prompt
            and not auth_blocker
            and not self.pty_generic_blocker_emitted.get(role_id, False)
        ):
            self.pty_pre_ready_unknown_chunks[role_id] += 1
            if self.pty_pre_ready_unknown_chunks[role_id] >= 3:
                self.pty_generic_blocker_emitted[role_id] = True
                blocker_detected = True
                preview = normalized[:160]
                synthetic_markers.append(
                    'SDD_ERROR: {"summary":"interactive operator input required","details":"launcher-backed role emitted unresolved interactive output before ready: '
                    + preview.replace('"', '\\"')
                    + '"}'
                )
        if self.pty_role_ready.get(role_id, False) and not blocker_detected:
            master_fd = self.pty_master_fds.get(role_id)
            if master_fd is not None:
                for buffered_text in self.pty_buffered_inputs.pop(role_id, []):
                    os.write(master_fd, (buffered_text + "\n").encode())
        return synthetic_markers

    def _contains_claude_trust_prompt(self, normalized_text: str) -> bool:
        return (
            "quick safety check" in normalized_text
            and "trust" in normalized_text
            and "folder" in normalized_text
        )

    def _contains_claude_ready_prompt(self, normalized_text: str) -> bool:
        return (
            ("auto mode on" in normalized_text and "ctrl+g to edit in vim" in normalized_text)
            or ("auto mode on" in normalized_text and "shift+tab to cycle" in normalized_text)
            or ("ctrl+g to edit in vim" in normalized_text)
        )

    def _contains_claude_auth_blocker(self, normalized_text: str) -> bool:
        return "needs auth" in normalized_text and "/mcp" in normalized_text

    def _contains_generic_confirmation_blocker(self, normalized_text: str) -> bool:
        return (
            "enter to confirm" in normalized_text
            and "esc to cancel" in normalized_text
            and "trust this folder" not in normalized_text
        )
