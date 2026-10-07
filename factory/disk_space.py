"""Shared disk-pressure checks using the existing task-cache pruning policy."""

from __future__ import annotations

import argparse
import errno
import fcntl
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time

log = logging.getLogger(__name__)


def disk_space_failure(value: object) -> bool:
    if isinstance(value, OSError) and value.errno == errno.ENOSPC:
        return True
    return any(message in str(value).lower() for message in (
        "no space left on device", "database or disk is full", "no disk space", "enospc",
        "disk full", "not enough disk space",
    ))


class DiskSpaceGuard:
    def __init__(self, workdir: Path, repo_root: Path, database_path: Path | None = None):
        self.workdir = workdir
        self.repo_root = repo_root
        self.database_path = database_path or workdir / "factory.sqlite3"
        self._lock = threading.Lock()
        self._last_check = float("-inf")

    def protected_tasks(self) -> list[str]:
        if not self.database_path.exists():
            return []
        # Read directly, without entering the guarded Database connection manager.
        with sqlite3.connect(self.database_path.as_uri() + "?mode=ro", uri=True, timeout=1) as connection:
            return [row[0] for row in connection.execute(
                "SELECT DISTINCT task_key FROM sessions WHERE status != 'completed'")]

    def check(self, *, current_key: str = "", force: bool = False) -> None:
        if os.environ.get("IOS_DERIVED_DATA_PRUNE_ENABLED", "1") == "0" or not self.workdir.exists():
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            if not force and now - self._last_check < 60:
                return
            self._last_check = now
            target = int(os.environ.get("IOS_MIN_FREE_DISK_GB", "50")) * 1024 ** 3
            if target < 0 or shutil.disk_usage(self.workdir).free >= target:
                return
            if not any(self.workdir.glob("*/tmp/verification/ios/derived-data")):
                return
            protected = self.protected_tasks()
            lock_root = self.workdir / ".locks"
            lock_root.mkdir(exist_ok=True)
            with (lock_root / "disk-space-prune.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                if shutil.disk_usage(self.workdir).free >= target:
                    return
                environment = dict(os.environ, SDD_WORKDIR=str(self.workdir))
                result = subprocess.run(
                    ["bash", str(self.repo_root / "scripts/prune-ios-cache.sh"), current_key, *protected],
                    env=environment, text=True, capture_output=True, timeout=55,
                )
                log.warning("Disk pressure cache cleanup: %s", (result.stdout + result.stderr).strip())
                if result.returncode:
                    log.warning("Cache cleanup exited %s; operator recovery may be required", result.returncode)
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
            # Never guess which active task can be deleted, or hide the original operation failure.
            log.warning("Disk pressure check could not safely prune caches: %s", error)
        finally:
            self._lock.release()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-key", default="")
    args = parser.parse_args()
    if os.environ.get("SDD_WORKDIR"):
        database = Path(os.environ["SDD_FACTORY_DB_PATH"]).resolve() if os.environ.get("SDD_FACTORY_DB_PATH") else None
        guard = DiskSpaceGuard(Path(os.environ["SDD_WORKDIR"]).resolve(), Path(__file__).resolve().parent.parent, database)
        guard.check(current_key=args.task_key, force=True)


if __name__ == "__main__":
    main()
