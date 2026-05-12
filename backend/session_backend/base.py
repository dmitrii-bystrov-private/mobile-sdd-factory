"""Abstract interface for long-lived role runtime backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.session_backend.runtime_models import RuntimeOutputChunk, RuntimeRoleHandle, RuntimeSessionHandle


class SessionBackend(ABC):
    """Abstract runtime backend used by the coordinator."""

    @abstractmethod
    def create_task_session(self, task_key: str) -> RuntimeSessionHandle:
        raise NotImplementedError

    @abstractmethod
    def spawn_role(self, session: RuntimeSessionHandle, role_name: str) -> RuntimeRoleHandle:
        raise NotImplementedError

    @abstractmethod
    def send_input(self, role: RuntimeRoleHandle, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_output(self, role: RuntimeRoleHandle) -> list[RuntimeOutputChunk]:
        raise NotImplementedError

    @abstractmethod
    def stop_role(self, role: RuntimeRoleHandle) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop_session(self, session: RuntimeSessionHandle) -> None:
        raise NotImplementedError
