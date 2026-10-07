"""Bind native conversations to an individual task/role workspace."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid


class SessionHistoryError(RuntimeError):
    pass


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def history_root(runner: str) -> Path:
    variable, default = ("CODEX_HOME", ".codex") if runner == "codex" else ("CLAUDE_CONFIG_DIR", ".claude")
    return Path(os.environ.get(variable, str(Path.home() / default))).resolve()


def metadata(path: Path, runner: str, workspace: Path) -> str | None:
    """Only read identity fields; never use transcript text to identify a role."""
    try:
        with path.open() as stream:
            for _ in range(256):
                line = stream.readline(262144)
                if not line:
                    break
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(item, dict):
                    continue
                if runner == "codex":
                    if item.get("type") != "session_meta":
                        continue
                    item = item.get("payload", {})
                    if not isinstance(item, dict):
                        continue
                    identity = item.get("id")
                else:
                    if item.get("isSidechain"):
                        continue
                    identity = item.get("sessionId")
                if isinstance(identity, str) and item.get("cwd") and Path(item["cwd"]).resolve() == workspace.resolve():
                    return str(uuid.UUID(identity))
    except (OSError, ValueError, TypeError):
        return None
    return None


def discover(workspace: Path, runner: str, started_at: float | None = None) -> dict | None:
    candidates = {}
    root = history_root(runner)
    if runner == "codex":
        for database in root.glob("state_*.sqlite"):
            try:
                with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1) as connection:
                    rows = connection.execute(
                        "SELECT id, rollout_path, created_at FROM threads WHERE cwd=? AND source='cli' AND archived=0",
                        (str(workspace.resolve()),)).fetchall()
                for identity, filename, created in rows:
                    if started_at is not None and created < started_at - 2:
                        continue
                    path = Path(filename)
                    if metadata(path, runner, workspace) == identity:
                        candidates[identity] = path
            except sqlite3.Error:
                continue
    else:
        project = root / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(workspace.resolve()))
        for path in project.glob("*.jsonl"):
            if started_at is not None and path.stat().st_mtime < started_at - 2:
                continue
            identity = metadata(path, runner, workspace)
            if identity:
                candidates[identity] = path
    if len(candidates) > 1:
        raise SessionHistoryError("More than one native conversation matches this role; an explicit session binding is required")
    if not candidates:
        return None
    identity, path = next(iter(candidates.items()))
    return {"version": 1, "runner": runner, "workspace": str(workspace.resolve()),
            "session_id": identity, "transcript_path": str(path)}


def binding(workspace: Path, runner: str) -> dict | None:
    path = workspace / "NATIVE_SESSION.json"
    if not path.exists():
        return discover(workspace, runner)
    try:
        record = json.loads(path.read_text())
    except ValueError as error:
        raise SessionHistoryError("Native session binding is not valid JSON") from error
    if not isinstance(record, dict) or record.get("version") != 1 or record.get("workspace") != str(workspace.resolve()):
        raise SessionHistoryError("Native session binding does not belong to this role workspace")
    if record.get("runner") != runner:
        return None
    if not record.get("session_id"):
        return discover(workspace, runner, record.get("started_at"))
    try:
        uuid.UUID(record["session_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise SessionHistoryError("Native session binding has an invalid conversation ID") from error
    if not record.get("transcript_path"):
        found = discover(workspace, runner, record.get("started_at"))
        if found is not None and found["session_id"] != record["session_id"]:
            raise SessionHistoryError("The saved conversation does not match the reserved role session ID")
        return found
    transcript = Path(record["transcript_path"])
    if not transcript.resolve().is_relative_to(history_root(runner)):
        raise SessionHistoryError("Native transcript is outside the configured runner history directory")
    if not transcript.exists():
        backup = workspace / "native-transcript.jsonl"
        if (not backup.exists() or metadata(backup, runner, workspace) != record["session_id"]
                or hashlib.sha256(backup.read_bytes()).hexdigest() != record.get("backup_digest")):
            raise SessionHistoryError("The bound native transcript and its checkpoint backup are unavailable")
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_bytes(backup.read_bytes())
    if metadata(transcript, runner, workspace) != record["session_id"]:
        raise SessionHistoryError("Native transcript identity or workspace changed")
    return record


def capture(workspace: Path, runner: str, *, required: bool) -> dict | None:
    if runner not in {"claude", "codex"}:
        return None
    record = binding(workspace, runner)
    if record is None:
        if required:
            raise SessionHistoryError("No saved native conversation is available for this routed role")
        return None
    transcript = Path(record["transcript_path"])
    content = transcript.read_bytes()
    try:
        json.loads(content.splitlines()[-1])
    except (ValueError, IndexError) as error:
        raise SessionHistoryError("Native transcript ends in an incomplete record; keep the runtime alive for recovery") from error
    backup = workspace / "native-transcript.jsonl"
    descriptor, temporary = tempfile.mkstemp(prefix="native-transcript.", dir=workspace)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, backup)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    record = dict(record, backup_digest=hashlib.sha256(content).hexdigest())
    atomic_json(workspace / "NATIVE_SESSION.json", record)
    return record


def launcher_identity(workspace: Path, runner: str, resume: bool) -> tuple[str, bool]:
    if runner not in {"claude", "codex"}:
        return "", False
    if resume:
        record = binding(workspace, runner)
        if record:
            atomic_json(workspace / "NATIVE_SESSION.json", record)
            return record["session_id"], True
    identity = str(uuid.uuid4()) if runner == "claude" else ""
    atomic_json(workspace / "NATIVE_SESSION.json", {
        "version": 1, "runner": runner, "workspace": str(workspace.resolve()),
        "session_id": identity, "started_at": datetime.now(UTC).timestamp(),
    })
    return identity, False
