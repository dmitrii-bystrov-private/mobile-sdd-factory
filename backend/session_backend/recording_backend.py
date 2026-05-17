"""Recording session backend for tests and fake route-layer acceptances."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from backend.session_backend.base import SessionBackend
from backend.session_backend.runtime_models import RuntimeOutputChunk, RuntimeRoleHandle, RuntimeSessionHandle


class RecordingSessionBackend(SessionBackend):
    """Minimal in-memory backend used as a test double."""

    def __init__(self) -> None:
        self.sent_inputs: dict[str, list[str]] = defaultdict(list)
        self.pending_outputs: dict[str, list[str]] = defaultdict(list)
        self.spawn_commands: dict[str, list[str]] = {}

    def create_task_session(self, task_key: str) -> RuntimeSessionHandle:
        return RuntimeSessionHandle(session_id=f"recording-{task_key}")

    def spawn_role(
        self,
        session: RuntimeSessionHandle,
        role_name: str,
        start_directory: Path | None = None,
        launch_command: list[str] | None = None,
    ) -> RuntimeRoleHandle:
        del start_directory
        role_id = f"{session.session_id}:{role_name}"
        self.spawn_commands[role_id] = list(launch_command or [])
        return RuntimeRoleHandle(
            role_id=role_id,
            session_id=session.session_id,
            backend_name="recording",
        )

    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        self.sent_inputs[role.role_id].append(text)

    def read_output(self, role: RuntimeRoleHandle) -> list[RuntimeOutputChunk]:
        outputs = self.pending_outputs.pop(role.role_id, [])
        return [RuntimeOutputChunk(role_id=role.role_id, text=text) for text in outputs]

    def stop_role(self, role: RuntimeRoleHandle) -> None:
        self.sent_inputs.pop(role.role_id, None)
        self.pending_outputs.pop(role.role_id, None)
        self.spawn_commands.pop(role.role_id, None)

    def stop_session(self, session: RuntimeSessionHandle) -> None:
        prefix = f"{session.session_id}:"
        for role_id in [role_id for role_id in self.sent_inputs if role_id.startswith(prefix)]:
            self.sent_inputs.pop(role_id, None)
            self.pending_outputs.pop(role_id, None)
            self.spawn_commands.pop(role_id, None)

    def get_sent_inputs(self, role_id: str) -> list[str]:
        return list(self.sent_inputs.get(role_id, []))

    def queue_output(self, role_id: str, text: str) -> None:
        self.pending_outputs[role_id].append(text)

    def simulate_output(self, role_id: str, text: str) -> None:
        self.queue_output(role_id, text)

    def get_spawn_command(self, role_id: str) -> list[str]:
        return list(self.spawn_commands.get(role_id, []))
