"""tmux-backed implementation of the session runtime abstraction."""

from __future__ import annotations

from collections import defaultdict

from backend.session_backend.base import SessionBackend
from backend.session_backend.runtime_models import RuntimeRoleHandle, RuntimeSessionHandle


class TmuxSessionBackend(SessionBackend):
    """Placeholder tmux backend.

    The implementation will be added after coordinator/state contracts stabilize.
    """

    def __init__(self) -> None:
        self.sent_inputs: dict[str, list[str]] = defaultdict(list)

    def create_task_session(self, task_key: str) -> RuntimeSessionHandle:
        return RuntimeSessionHandle(session_id=f"tmux:{task_key}")

    def spawn_role(self, session: RuntimeSessionHandle, role_name: str) -> RuntimeRoleHandle:
        return RuntimeRoleHandle(
            role_id=f"{session.session_id}:{role_name}",
            session_id=session.session_id,
            backend_name="tmux",
        )

    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        self.sent_inputs[role.role_id].append(text)

    def stop_role(self, role: RuntimeRoleHandle) -> None:
        del role

    def stop_session(self, session: RuntimeSessionHandle) -> None:
        del session

    def get_sent_inputs(self, role_id: str) -> list[str]:
        return list(self.sent_inputs.get(role_id, []))
