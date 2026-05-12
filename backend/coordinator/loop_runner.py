"""In-process coordinator loop runner."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable


LoopCallback = Callable[[], tuple[object | None, int, int]]


@dataclass(slots=True)
class LoopRunnerStatus:
    running: bool
    interval_seconds: float
    tick_count: int
    last_session_count: int
    last_chunk_count: int


class CoordinatorLoopRunner:
    """Runs coordinator loop ticks on a background thread."""

    def __init__(self, callback: LoopCallback, interval_seconds: float = 1.0) -> None:
        self._callback = callback
        self._interval_seconds = interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._tick_count = 0
        self._last_session_count = 0
        self._last_chunk_count = 0

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="sdd-factory-loop")
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                return False
            self._stop_event.set()
        thread.join(timeout=self._interval_seconds * 2)
        return True

    def status(self) -> LoopRunnerStatus:
        thread = self._thread
        return LoopRunnerStatus(
            running=thread is not None and thread.is_alive(),
            interval_seconds=self._interval_seconds,
            tick_count=self._tick_count,
            last_session_count=self._last_session_count,
            last_chunk_count=self._last_chunk_count,
        )

    def run_once(self) -> tuple[object | None, int, int]:
        result = self._callback()
        _, session_count, chunk_count = result
        self._tick_count += 1
        self._last_session_count = session_count
        self._last_chunk_count = chunk_count
        return result

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self._interval_seconds)
