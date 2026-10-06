#!/usr/bin/env python3
"""Run the native e2e gate in an isolated test checkout, without Jira or MR writes."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from backend.coordinator.verification_strategy import materialize_verification_strategy
from factory.e2e.config import Machine
from factory.e2e.runner import ROOT, execute, git, validate_verdict, verify, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("ios", "android", "both"), default="both")
    parser.add_argument("--strategy", type=Path, required=True, help="Task-provided verification-strategy.json with execution recipes")
    args = parser.parse_args()
    machine = Machine.from_env()
    workdir = Path(tempfile.mkdtemp(prefix="constellation-e2e-live-")).resolve()
    task_key = "QA-900001"
    task_root = workdir / task_key
    (task_root / "spec").mkdir(parents=True)
    baseline = git(machine.repo, "rev-parse", "origin/master")
    git(machine.repo, "worktree", "add", "--detach", str(task_root / "repo"), baseline)
    try:
        platforms = ("ios", "android") if args.platform == "both" else (args.platform,)
        provided = json.loads(args.strategy.read_text())["e2e"]
        for name in provided.get("support_files", []):
            source_file = (args.strategy.resolve().parent.parent / name).resolve()
            target_file = (task_root / name).resolve()
            if not source_file.is_relative_to(args.strategy.resolve().parent.parent) or not target_file.is_relative_to(task_root):
                raise ValueError("Support files must belong to the source and acceptance task snapshots")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
        write_json(task_root / "spec/verification-strategy.json", {"e2e": {
            "platforms": {p: provided["platforms"][p] for p in platforms}, "support_files": provided.get("support_files", [])}})
        strategy, _ = materialize_verification_strategy(
            task_key=task_key, workdir_root=workdir, repo_root=ROOT, work_item_id=900001,
        )
        verdict = verify(task_key, task_root, strategy, machine)
        validate_verdict(task_root, 900001)
        if "android" in platforms:
            listed = execute([str(machine.android_sdk / "platform-tools/adb"), "devices"])
            if any(line.split()[0] == machine.android_serial for line in listed.splitlines() if line.split()):
                raise RuntimeError("Reserved Android emulator is still running")
        for cleanup in verdict.get("ios_simulator_cleanup", []):
            devices = json.loads(execute(["xcrun", "simctl", "list", "devices", "-j"]))["devices"]
            device = next(item for entries in devices.values() for item in entries if item["udid"] == cleanup["udid"])
            if not cleanup["stopped"] or device["state"] != "Shutdown":
                raise RuntimeError("Dedicated iOS simulator is still running")
        print(json.dumps({"result": verdict["result"], "report": verdict["report_path"],
                          "android_emulator_stopped": verdict.get("android_emulator_stopped"),
                          "ios_simulator_cleanup": verdict.get("ios_simulator_cleanup", []),
                          "phases": [{"platform": r["platform"], "phase": r["phase"], "ok": r["ok"],
                                      "passed": len((r["results"] or {}).get("passed", []))}
                                     for r in verdict["receipts"]]}, indent=2))
        return 0 if verdict["result"] == "passed" else 1
    finally:
        git(machine.repo, "worktree", "remove", "--force", str(task_root / "repo"))
        marker = ROOT / ".ts/runtime/e2e-live-acceptance-root"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(workdir))


if __name__ == "__main__":
    raise SystemExit(main())
