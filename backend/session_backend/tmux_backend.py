"""tmux-backed implementation of the session runtime abstraction."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
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
        self.runtime_root = runtime_root or Path.cwd() / "workdir" / "factory-runtime"
        self.sent_inputs: dict[str, list[str]] = defaultdict(list)
        self.pending_outputs: dict[str, list[str]] = defaultdict(list)
        self.last_captured_output: dict[str, str] = {}
        self._available = shutil.which("tmux") is not None
        self._effective_mode = self._resolve_mode(mode)

    @property
    def effective_mode(self) -> str:
        return self._effective_mode

    def _resolve_mode(self, mode: str) -> str:
        if mode == "recording":
            return "recording"
        if mode == "tmux":
            return "tmux"
        return "tmux" if self._available else "recording"

    def _sanitize(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "-", value)

    def _socket_path(self, session_name: str) -> Path:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        return self.runtime_root / f"{session_name}.sock"

    def _tmux(self, socket_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["tmux", "-S", str(socket_path), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def create_task_session(self, task_key: str) -> RuntimeSessionHandle:
        session_name = f"sdd-{self._sanitize(task_key)}"
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session_name)
            result = self._tmux(socket_path, "new-session", "-d", "-s", session_name, "sh")
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to create tmux session")
        return RuntimeSessionHandle(session_id=session_name)

    def spawn_role(self, session: RuntimeSessionHandle, role_name: str) -> RuntimeRoleHandle:
        role_window = self._sanitize(role_name)
        role_id = f"{session.session_id}:{role_window}"
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session.session_id)
            result = self._tmux(
                socket_path,
                "new-window",
                "-d",
                "-t",
                session.session_id,
                "-n",
                role_window,
                "sh",
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to create tmux window")
        return RuntimeRoleHandle(
            role_id=role_id,
            session_id=session.session_id,
            backend_name="tmux",
        )

    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        self.sent_inputs[role.role_id].append(text)
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(role.session_id)
            result = self._tmux(socket_path, "send-keys", "-t", role.role_id, text, "Enter")
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Failed to send tmux input")

    def read_output(self, role: RuntimeRoleHandle) -> list[RuntimeOutputChunk]:
        if self._effective_mode == "recording":
            outputs = self.pending_outputs.pop(role.role_id, [])
            return [RuntimeOutputChunk(role_id=role.role_id, text=text) for text in outputs]

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

    def stop_session(self, session: RuntimeSessionHandle) -> None:
        if self._effective_mode == "tmux":
            socket_path = self._socket_path(session.session_id)
            self._tmux(socket_path, "kill-session", "-t", session.session_id)
            if socket_path.exists():
                socket_path.unlink()

    def get_sent_inputs(self, role_id: str) -> list[str]:
        return list(self.sent_inputs.get(role_id, []))

    def simulate_output(self, role_id: str, text: str) -> None:
        self.pending_outputs[role_id].append(text)
