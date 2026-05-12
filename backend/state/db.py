"""Low-level SQLite access helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


class Database:
    """Simple SQLite connection manager for the local backend."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.migrations_dir = Path(__file__).resolve().parent / "migrations"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create migration metadata and apply known SQL migrations."""

        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version TEXT PRIMARY KEY,
                  applied_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            applied_versions = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }

            for migration_path in sorted(self.migrations_dir.glob("*.sql")):
                version = migration_path.name
                if version in applied_versions:
                    continue

                connection.executescript(migration_path.read_text())
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)",
                    (version,),
                )
