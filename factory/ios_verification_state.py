"""Native lifecycle evidence for the factory iOS verification command."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import uuid


def state_path(task_root: Path) -> Path:
    return task_root / "tmp/verification/ios/execution-state.json"


def source_sha(task_root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(task_root / "repo"), "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()


def runner_is_alive(pid: int, task_key: str) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True, timeout=5)
        argv = shlex.split(command.strip())
        return len(argv) >= 3 and argv[-1] == task_key and Path(argv[-2]).parts[-2:] == ("scripts", "ios-verify.sh")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def lock_owner_is_ancestor(owner_pid: int) -> bool:
    pid = os.getpid()
    try:
        for _ in range(64):
            if pid == owner_pid:
                return True
            if pid <= 1:
                return False
            pid = int(subprocess.check_output(["ps", "-p", str(pid), "-o", "ppid="], text=True, timeout=5).strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return False


def read_active_run(task_root: Path, work_item_id: int, dispatched_at: datetime | None) -> dict | None:
    try:
        record = json.loads(state_path(task_root).read_text())
        started = datetime.fromisoformat(record["started_at"])
        if (record.get("version") != 1 or record.get("task_key") != task_root.name
                or record.get("work_item_id") != work_item_id or not record.get("run_id")
                or record.get("state") not in {"running", "waiting_for_resource"}
                or started.tzinfo is None or dispatched_at is None or started < dispatched_at
                or not runner_is_alive(record.get("runner_pid"), task_root.name)
                or record.get("source_sha") != source_sha(task_root)):
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def write_state(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True) + "\n")
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "phase", "wait", "running", "finish", "owner-is-ancestor"))
    parser.add_argument("task_key")
    parser.add_argument("--run-id")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--phase")
    parser.add_argument("--resource")
    parser.add_argument("--lock-dir")
    parser.add_argument("--exit-code", type=int)
    args = parser.parse_args(argv)
    if args.action == "owner-is-ancestor":
        return 0 if lock_owner_is_ancestor(args.pid) else 1
    task_root = Path(os.environ["SDD_WORKDIR"]) / args.task_key
    path = state_path(task_root)
    now = datetime.now(UTC).isoformat()
    if args.action == "start":
        if path.exists():
            previous = json.loads(path.read_text())
            if previous.get("state") in {"running", "waiting_for_resource"} and runner_is_alive(previous.get("runner_pid"), args.task_key):
                raise RuntimeError("An iOS verification command is already running for this task; wait for its completion")
        strategy = json.loads((task_root / "spec/verification-strategy.json").read_text())
        record = {"version": 1, "task_key": args.task_key, "work_item_id": strategy.get("work_item_id"),
                  "source_sha": source_sha(task_root), "run_id": uuid.uuid4().hex,
                  "runner_pid": args.pid, "started_at": now, "state": "running", "phase": None}
    else:
        record = json.loads(path.read_text())
        if record.get("run_id") != args.run_id:
            return 0
        record.pop("resource", None)
        if args.action == "finish":
            record.update(state="finished", exit_code=args.exit_code)
        elif args.action == "wait":
            lock = Path(args.lock_dir)
            try:
                owner = (lock / "owner.pid").read_text().strip()
            except OSError:
                owner = "unknown"
            record.update(state="waiting_for_resource", resource={"name": args.resource, "owner_pid": owner})
        else:
            record["state"] = "running"
            if args.phase:
                record["phase"] = args.phase
    record["updated_at"] = now
    write_state(path, record)
    if args.action == "start":
        print(record["run_id"])
    elif args.action == "wait":
        print("SDD_PROGRESS: " + json.dumps({"work_item_id": record["work_item_id"],
              "summary": f"Waiting for {args.resource}; owner PID {record['resource']['owner_pid']}. Resource contention is expected; keep waiting for this command."}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
