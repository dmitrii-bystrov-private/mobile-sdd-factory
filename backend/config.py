"""Configuration for the SDD Factory backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration resolved from the local environment."""

    repo_root: Path
    workdir_root: Path
    database_path: Path
    runtime_backend: str
    runtime_root: Path
    agent_launcher_command: tuple[str, ...]
    loop_interval_seconds: float
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"


def load_config() -> AppConfig:
    """Load application configuration from environment variables."""

    repo_root = Path(__file__).resolve().parent.parent
    default_workdir_root = repo_root / "workdir"
    workdir_root = Path(os.environ.get("SDD_WORKDIR", default_workdir_root))
    database_path = Path(
        os.environ.get("SDD_FACTORY_DB_PATH", default_workdir_root / "factory.sqlite3")
    )

    return AppConfig(
        repo_root=repo_root,
        workdir_root=workdir_root,
        database_path=database_path,
        runtime_backend=os.environ.get("SDD_FACTORY_RUNTIME_BACKEND", "auto"),
        runtime_root=Path(
            os.environ.get("SDD_FACTORY_RUNTIME_ROOT", default_workdir_root / "factory-runtime")
        ),
        agent_launcher_command=tuple(
            os.environ.get("SDD_FACTORY_AGENT_LAUNCHER", "auto").split()
        ),
        loop_interval_seconds=float(os.environ.get("SDD_FACTORY_LOOP_INTERVAL_SECONDS", "1.0")),
        host=os.environ.get("SDD_FACTORY_HOST", "127.0.0.1"),
        port=int(os.environ.get("SDD_FACTORY_PORT", "8000")),
        log_level=os.environ.get("SDD_FACTORY_LOG_LEVEL", "INFO"),
    )
