"""Deterministic local pytest/Appium gate and source-bound verification receipts."""

from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from factory.e2e.config import E2EError, Machine
from factory.e2e.execution import CONTRACT_VERSION, E2EPlanError, command, configurations, render, selection, support_digests
from factory.e2e.selection import eligible_checks

ROOT = Path(__file__).resolve().parents[2]
CHROMEDRIVER_FEATURE = "uiautomator2:chromedriver_autodownload"


def execute(command, *, cwd=None, env=None, timeout=30):
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise E2EError(f"{Path(str(command[0])).name} failed: {result.stderr[-1500:]}")
    return result.stdout.strip()


def git(repo, *args):
    return execute(["git", "-C", str(repo), *args])


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise E2EError(f"Cannot read {path}: {exc}") from exc


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(repo):
    return {"sha": git(repo, "rev-parse", "HEAD"), "dirty": bool(git(repo, "status", "--porcelain"))}


def validate_source(repo, recorded, *, allow_documentation_changes=False):
    """Keep exact source binding except for committed regular documentation at delivery."""
    current = source(repo)
    if recorded == current:
        return []
    stale = "E2E evidence is stale or belongs to another work item"
    if (not allow_documentation_changes or not isinstance(recorded, dict)
            or recorded.get("dirty") is not False or current["dirty"]):
        raise E2EError(stale)
    verified_sha = recorded.get("sha", "")
    if not isinstance(verified_sha, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", verified_sha):
        raise E2EError(stale)
    try:
        git(repo, "merge-base", "--is-ancestor", verified_sha, current["sha"])
    except E2EError as exc:
        raise E2EError("E2E evidence is stale: the verified commit is not an ancestor of the delivery commit") from exc
    entries = git(repo, "diff", "--raw", "--no-abbrev", "--no-renames", "-z", verified_sha, current["sha"], "--").split("\0")
    changed = []
    for index in range(0, len(entries) - 1, 2):
        header, name = entries[index:index + 2]
        old_mode, new_mode = header.lstrip(":").split()[:2]
        if (Path(name).suffix.lower() not in {".md", ".markdown", ".rst", ".adoc"}
                or old_mode not in {"000000", "100644"} or new_mode not in {"000000", "100644"}):
            raise E2EError(f"E2E evidence is stale: {name} changed after verification; a fresh gate is required")
        changed.append(name)
    return changed


def doctor(machine):
    expected = read_json(Path(__file__).with_name("toolchain.json"))
    python = execute([str(machine.python), "-c", "import platform; print(platform.python_version())"])
    appium = execute([machine.appium, "--version"])
    drivers = json.loads(execute([machine.appium, "driver", "list", "--installed", "--json"]))
    versions = {name: value.get("version") for name, value in drivers.items()}
    mismatches = []
    if machine.ios_pool:
        try:
            runtimes = {ios_simulator(udid)["version"] for udid in machine.ios_pool}
            if len(runtimes) != 1:
                mismatches.append("Dedicated iOS pool simulators must use the same runtime")
        except (E2EError, OSError, subprocess.SubprocessError) as exc:
            mismatches.append(str(exc))
    if not python.startswith(expected["python"] + "."):
        mismatches.append(f"Python {expected['python']} required, found {python}")
    if appium != expected["appium"]:
        mismatches.append(f"Appium {expected['appium']} required, found {appium}")
    for name, version in expected["drivers"].items():
        if versions.get(name) != version:
            mismatches.append(f"{name} {version} required, found {versions.get(name)}")
    running_server = appium_server_status(machine)
    if running_server is not None:
        try:
            validate_appium_server(machine, running_server)
        except E2EError as exc:
            mismatches.append(str(exc))
    return {"ok": not mismatches, "python": python, "appium": appium, "drivers": versions,
            "repo": str(machine.repo), "errors": mismatches}


def resolve_app(machine, platform, requested=None):
    if requested:
        path = Path(requested["path"]).expanduser().resolve()
        receipt = requested
    else:
        if machine.build_root is None:
            raise E2EError("Set E2E_BUILD_ROOT to the local app build store")
        candidates = []
        for file in (machine.build_root / platform / "artifacts").glob("master-*.json"):
            data = read_json(file)
            if data.get("label") == "master" and data.get("branch") == "master" and data.get("platform") == platform and data.get("sha") and data.get("dirty") is False:
                candidates.append((data.get("built_at", ""), file, data))
        if not candidates:
            raise E2EError(f"No clean master {platform} build receipt in E2E_BUILD_ROOT")
        _, file, receipt = max(candidates, key=lambda item: item[0])
        path = file.with_suffix(".app" if platform == "ios" else ".apk").resolve()
    if not receipt.get("sha") or receipt.get("dirty"):
        raise E2EError("An app build must have a known clean source SHA")
    if not path.exists() or path.suffix != (".app" if platform == "ios" else ".apk"):
        raise E2EError(f"Missing {platform} app artifact: {path}")
    fingerprint = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    for file in files:
        fingerprint.update(str(file.relative_to(path) if path.is_dir() else file.name).encode())
        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                fingerprint.update(chunk)
    return {"path": str(path), "sha": receipt["sha"], "label": receipt.get("label", "explicit"),
            "artifact_digest": fingerprint.hexdigest()}


def pin_app(task_root, machine, platform, app):
    """Keep the chosen artifact alive independently of shared build-store cleanup."""
    original = Path(app["path"])
    target = task_root / "tmp/e2e/app-artifacts" / app["artifact_digest"] / original.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.parent / (uuid.uuid4().hex + original.suffix)
        try:
            if original.is_dir():
                shutil.copytree(original, temporary, symlinks=True)
            else:
                shutil.copy2(original, temporary)
            temporary.replace(target)
        finally:
            if temporary.is_dir():
                shutil.rmtree(temporary)
            elif temporary.exists():
                temporary.unlink()
    pinned = resolve_app(machine, platform, dict(app, path=str(target)))
    if pinned["artifact_digest"] != app["artifact_digest"]:
        raise E2EError("App artifact changed while being pinned for verification")
    return pinned


def ios_simulator(udid):
    if not udid:
        raise E2EError("Configure the dedicated iOS pool or E2E_IOS_SIMULATOR_UDID")
    inventory = json.loads(execute(["xcrun", "simctl", "list", "devices", "-j"]))
    for runtime, devices in inventory["devices"].items():
        found = next((entry for entry in devices if entry["udid"] == udid), None)
        if found:
            version = re.search(r"iOS-(\d+(?:-\d+)+)$", runtime)
            if not version or not found.get("isAvailable", True):
                raise E2EError(f"Configured iOS simulator is unavailable: {udid}")
            return dict(found, version=version[1].replace("-", "."))
    raise E2EError(f"Configured iOS simulator does not exist: {udid}")


@contextmanager
def reserve_ios(machine, lock_root, deadline):
    """Lease one dedicated simulator; never acquire the workspace's shared device."""
    announced = False
    while True:
        for udid in machine.ios_pool:
            with (lock_root / f"ios-{udid}.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                try:
                    yield replace(machine, ios_udid=udid)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise E2EError("Dedicated iOS pool remained busy until the verification time limit")
        if not announced:
            print("Waiting for a free dedicated iOS simulator", file=sys.stderr, flush=True)
            announced = True
        time.sleep(min(0.25, remaining))


def device(machine, platform, *, boot=False):
    if platform == "ios":
        if machine.ios_pool and machine.ios_udid not in machine.ios_pool:
            raise E2EError("Acquire a dedicated iOS pool lease before accessing a simulator")
        found = ios_simulator(machine.ios_udid)
        if boot and found["state"] != "Booted":
            execute(["xcrun", "simctl", "boot", machine.ios_udid])
        if boot:
            execute(["xcrun", "simctl", "bootstatus", machine.ios_udid, "-b"], timeout=300)
        target = {"udid": machine.ios_udid, "version": found["version"]}
        if machine.ios_pool:
            slot = machine.ios_pool.index(machine.ios_udid)
            target.update(wda_local_port=machine.ios_wda_port_base + slot,
                          mjpeg_server_port=machine.ios_mjpeg_port_base + slot,
                          derived_data_path=str(machine.ios_wda_root / machine.ios_udid))
        return target
    adb = machine.android_sdk / "platform-tools/adb"
    listed = execute([str(adb), "devices"])
    if boot and f"{machine.android_serial}\tdevice" not in listed:
        if not machine.android_avd or not re.fullmatch(r"emulator-\d+", machine.android_serial):
            raise E2EError("Set E2E_ANDROID_AVD and E2E_ANDROID_SERIAL")
        subprocess.Popen([str(machine.android_sdk / "emulator/emulator"), "-avd", machine.android_avd,
                          "-port", machine.android_serial.split("-")[1], "-no-snapshot-save"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        execute([str(adb), "-s", machine.android_serial, "wait-for-device"], timeout=300)
        deadline = time.monotonic() + 300
        while execute([str(adb), "-s", machine.android_serial, "shell", "getprop", "sys.boot_completed"]) != "1":
            if time.monotonic() >= deadline:
                raise E2EError("Android emulator boot timed out")
            time.sleep(1)
    return {"serial": machine.android_serial, "adb": str(adb)}


def install(machine, platform, app, target):
    if platform == "ios":
        info = plistlib.loads((Path(app["path"]) / "Info.plist").read_bytes())
        target["bundle_id"] = info["CFBundleIdentifier"]
        execute(["xcrun", "simctl", "install", target["udid"], app["path"]], timeout=180)
    else:
        execute([target["adb"], "-s", target["serial"], "install", "-r", "-g", app["path"]], timeout=180)


def shutdown_android(machine):
    """Stop the reserved emulator and wait until adb no longer lists it."""
    adb = str(machine.android_sdk / "platform-tools/adb")
    def present():
        return any(line.split()[0] == machine.android_serial for line in
                   execute([adb, "devices"]).splitlines() if line.split())
    if not present():
        return
    execute([adb, "-s", machine.android_serial, "emu", "kill"])
    deadline = time.monotonic() + 20
    while present():
        if time.monotonic() >= deadline:
            raise E2EError("Reserved Android emulator did not shut down")
        time.sleep(0.25)


def finish_android(machine, verdict):
    try:
        shutdown_android(machine)
        verdict["android_emulator_stopped"] = True
    except (E2EError, OSError, subprocess.SubprocessError) as exc:
        verdict["android_emulator_stopped"] = False
        verdict.setdefault("cleanup_warnings", []).append(f"Android emulator shutdown failed: {exc}")


def shutdown_ios(machine):
    if ios_simulator(machine.ios_udid)["state"] == "Shutdown":
        return
    execute(["xcrun", "simctl", "shutdown", machine.ios_udid])
    deadline = time.monotonic() + 20
    while ios_simulator(machine.ios_udid)["state"] != "Shutdown":
        if time.monotonic() >= deadline:
            raise E2EError("Dedicated iOS simulator did not shut down")
        time.sleep(0.25)


def finish_ios(machine, verdict):
    record = {"udid": machine.ios_udid, "stopped": False}
    try:
        shutdown_ios(machine)
        record["stopped"] = True
    except (E2EError, OSError, subprocess.SubprocessError) as exc:
        verdict.setdefault("cleanup_warnings", []).append(f"iOS simulator shutdown failed: {exc}")
    verdict.setdefault("ios_simulator_cleanup", []).append(record)


def appium_server_status(machine):
    url = f"http://127.0.0.1:{machine.appium_port}/wd/hub/status"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            value = json.load(response).get("value", {})
    except (OSError, ValueError):
        return None
    return value if value.get("ready") else None


def validate_appium_server(machine, value):
    expected_version = read_json(Path(__file__).with_name("toolchain.json"))["appium"]
    if value.get("build", {}).get("version") != expected_version:
        raise E2EError(
            f"Appium on port {machine.appium_port} does not match pinned version {expected_version}; "
            "stop the old server before retrying the gate"
        )
    try:
        pids = set(execute(["lsof", "-nP", "-t", f"-iTCP:{machine.appium_port}", "-sTCP:LISTEN"]).split())
        if len(pids) != 1 or not next(iter(pids)).isdigit():
            raise E2EError("Expected one local listener process")
        arguments = shlex.split(execute(["ps", "-ww", "-p", next(iter(pids)), "-o", "command="]))
    except (E2EError, OSError, ValueError, subprocess.SubprocessError) as exc:
        raise E2EError(f"Cannot inspect shared Appium launch flags on port {machine.appium_port}; "
                       "check lsof/ps access before retrying verification") from exc
    def features(flag):
        values = []
        for index, argument in enumerate(arguments):
            if argument.startswith(flag + "="):
                values.append(argument.split("=", 1)[1])
            elif argument == flag and index + 1 < len(arguments):
                values.append(arguments[index + 1])
        return {feature.strip().lower() for value in values for feature in value.split(",")}
    matching = {CHROMEDRIVER_FEATURE, "*:chromedriver_autodownload"}
    if not features("--allow-insecure") & matching or features("--deny-insecure") & matching:
        raise E2EError(f"Shared Appium on port {machine.appium_port} requires --allow-insecure "
                       f"{CHROMEDRIVER_FEATURE} without a matching --deny-insecure; "
                       "restart it with this flag after active runs finish, then retry verification")


def ensure_server(machine, logs):
    def ready():
        value = appium_server_status(machine)
        if value is None:
            return False
        validate_appium_server(machine, value)
        return True
    if ready():
        return
    with logs.open("ab") as handle:
        subprocess.Popen([machine.appium, "-a", "127.0.0.1", "-p", str(machine.appium_port),
                          "--base-path", "/wd/hub", "--allow-insecure", CHROMEDRIVER_FEATURE], stdout=handle, stderr=handle,
                         env={**os.environ, "ANDROID_HOME": str(machine.android_sdk)}, start_new_session=True)
    for _ in range(60):
        if ready():
            return
        time.sleep(0.5)
    raise E2EError(f"Appium did not start; see {logs}")


def execution_environment(machine, repo, platform, target, config, context, app=None, fresh=False):
    env = dict(os.environ)
    for name in config.get("unset_environment", []):
        env.pop(name, None)
    env.update({name: render(value, context) for name, value in config.get("environment", {}).items()})
    env.update({"FACTORY_E2E_PLATFORM": platform, "FACTORY_E2E_DEVICE_ID": context["device_id"],
                "FACTORY_E2E_PLATFORM_VERSION": context["platform_version"],
                "FACTORY_E2E_APPIUM_PORT": context["appium_port"],
                "FACTORY_E2E_APPIUM_URL": f"http://127.0.0.1:{context['appium_port']}/wd/hub",
                "FACTORY_E2E_FRESH_INSTALL": "1" if fresh else "0", "FACTORY_E2E_APP_ID": context["application_id"],
                "FACTORY_E2E_ADB": context["adb"], "FACTORY_E2E_APP": context["app_path"],
                "FACTORY_E2E_RESULTS": context["results"], "FACTORY_E2E_COLLECTION": context["collected"],
                "FACTORY_E2E_COLLECTION_METADATA": context.get("collection_metadata", ""),
                "FACTORY_E2E_DIAGNOSTIC": context.get("diagnostic", "")})
    env.pop("FACTORY_E2E_APPIUM_CAPABILITIES", None)
    if platform == "ios" and machine.ios_pool:
        env["FACTORY_E2E_APPIUM_CAPABILITIES"] = json.dumps({
            "appium:udid": target["udid"], "appium:wdaLocalPort": target["wda_local_port"],
            "appium:mjpegServerPort": target["mjpeg_server_port"],
            "appium:derivedDataPath": target["derived_data_path"], "appium:shutdownOtherSimulators": False})
    return env


def junit_results(path):
    results = {"passed": [], "failed": [], "skipped": []}
    tree = ET.parse(path)
    for case in tree.iter("testcase"):
        name = case.get("classname", "") + "::" + case.get("name", "")
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        status = "failed" if failure is not None else "skipped" if case.find("skipped") is not None else "passed"
        results[status].append({"test": name, "details": (failure.text or "")[-2500:] if failure is not None else ""})
    return results


def execution_context(machine, repo, platform, target, app, policy, folder, name):
    config = policy["_configurations"][platform]
    context = {"python": str(machine.python), "repo": str(repo), "integration_repo": str(machine.repo), "task_root": str(policy["_task_root"]),
               "platform": platform, "device_id": target.get("udid", target.get("serial", "")),
               "platform_version": target.get("version", ""),
               "application_id": target.get("bundle_id", config.get("application_id", "")),
               "app_path": (app or {}).get("path", ""), "appium_port": str(machine.appium_port),
               "android_sdk": str(machine.android_sdk), "adb": target.get("adb", ""),
               "factory_plugin_dir": str(Path(__file__).parent), "junit": str(folder / f"{platform}-{name}.xml"),
               "results": str(folder / f"{platform}-{name}-outcomes.json"),
               "collected": str(folder / f"{platform}-{name}-collection.json"),
               "diagnostic": str(folder / f"{platform}-{name}-diagnostic.json"),
               "eligibility": str(folder / f"{platform}-{name}-checks.json"),
               "collection_metadata": str(folder / f"{platform}-{name}-metadata.json"),
               "selection_metadata": str(folder / f"{platform}-selection-metadata.json"),
               "test_timeout_seconds": str(policy["test_timeout_seconds"])}
    context.update({name: str(target.get(name, "")) for name in
                    ("wda_local_port", "mjpeg_server_port", "derived_data_path")})
    return context


def run_command(argv, repo, env, log, timeout, policy, platform, name):
    with log.open("w") as handle:
        process = subprocess.Popen(argv, cwd=repo, env=env,
                                   stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        except BaseException as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            if isinstance(exc, subprocess.TimeoutExpired):
                limit = "total verification time limit" if "_deadline" in policy else "phase time limit"
                raise E2EError(f"{platform} {name} timed out: {limit} ({policy['run_timeout_seconds']}s) exhausted; see {log}") from exc
            raise


def check_selection(machine, repo, platform, target, app, policy, folder, candidates):
    """Execute the bound project's catalog adapter before installing or running apps."""
    config = policy["_configurations"][platform]
    context = execution_context(machine, repo, platform, target, app, policy, folder, "eligibility")
    log, path = folder / f"{platform}-eligibility.log", Path(context["eligibility"])
    started = datetime.now(timezone.utc)
    timeout = policy.get("_deadline", time.monotonic() + policy["run_timeout_seconds"]) - time.monotonic()
    if timeout <= 0:
        raise E2EError("E2E verification exceeded the configured total time limit")
    env = execution_environment(machine, repo, platform, target, config, context, app)
    env["FACTORY_E2E_ELIGIBILITY"] = str(path)
    code = run_command(command(config, "eligibility", candidates, context), repo, env, log, timeout, policy, platform, "eligibility")
    if code != 0:
        raise E2EPlanError(f"Project active coverage could not be checked; no unfiltered fallback is allowed. See {log}")
    try:
        report = read_json(path)
        active = eligible_checks(report, candidates, config, policy)
        checked = datetime.fromisoformat(report["checked_at"].replace("Z", "+00:00"))
        if not started.timestamp() - 1 <= checked.timestamp() <= datetime.now(timezone.utc).timestamp() + 1:
            raise E2EPlanError("Project active coverage must be checked during the current selection command")
    except E2EError as exc:
        raise E2EPlanError(f"{exc} Selection evidence: {path}; log: {log}") from exc
    receipt = {"phase": "eligibility", "platform": platform, "source": source(repo), "app": app, "device": target,
               "selectors": candidates, "collected": active, "exit_code": code, "ok": True,
               "log": str(log), "log_digest": digest(log), "junit_digest": None, "results": None,
               "eligibility_path": str(path), "eligibility_digest": digest(path), "eligibility": report}
    file = folder / f"{platform}-eligibility.json"
    write_json(file, receipt)
    receipt["path"] = str(file)
    return receipt


def phase(machine, repo, platform, target, app, policy, folder, name, selectors, *, collect=False, fresh=False):
    log, junit = folder / f"{platform}-{name}.log", folder / f"{platform}-{name}.xml"
    outcomes_path = folder / f"{platform}-{name}-outcomes.json"
    collection_path = folder / f"{platform}-{name}-collection.json"
    diagnostic_path = folder / f"{platform}-{name}-diagnostic.json"
    config = policy["_configurations"][platform]
    context = execution_context(machine, repo, platform, target, app, policy, folder, name)
    argv = command(config, "collect" if collect else "run", selectors, context)
    started = time.monotonic()
    timeout = min(policy["run_timeout_seconds"], policy.get("_deadline", started + policy["run_timeout_seconds"]) - started)
    if timeout <= 0:
        raise E2EError("E2E verification exceeded the configured total time limit")
    env = execution_environment(machine, repo, platform, target, config, context, app, fresh)
    if collect and policy.get("selection_adapter") == "pytest_testrail":
        env["PYTHONPATH"] = context["factory_plugin_dir"] + os.pathsep + env.get("PYTHONPATH", "")
        plugins = [item for item in env.get("PYTEST_PLUGINS", "").split(",") if item]
        env["PYTEST_PLUGINS"] = ",".join(dict.fromkeys([*plugins, "pytest_evidence"]))
    if fresh and not collect:
        if not app or not context["application_id"]:
            raise E2EError("Fresh installation requires an app and its application identifier")
        if platform == "ios":
            execute(["xcrun", "simctl", "uninstall", context["device_id"], context["application_id"]], timeout=min(60, timeout))
        else:
            execute([context["adb"], "-s", context["device_id"], "uninstall", context["application_id"]], timeout=min(60, timeout))
        install(machine, platform, app, target)
        timeout = min(policy["run_timeout_seconds"], policy.get("_deadline", started + policy["run_timeout_seconds"]) - time.monotonic())
        if timeout <= 0:
            raise E2EError("E2E verification exceeded the configured total time limit during fresh installation")
    code = run_command(argv, repo, env, log, timeout, policy, platform, name)
    results = junit_results(junit) if junit.exists() and not collect else None
    selected = read_json(collection_path) if collect and collection_path.exists() else []
    if not isinstance(selected, list) or any(not isinstance(node, str) or not node for node in selected):
        raise E2EError("Collection command must produce a JSON array of check identifiers")
    outcomes = read_json(outcomes_path) if outcomes_path.exists() else []
    if not isinstance(outcomes, list) or any(not isinstance(item, dict) or not item.get("nodeid")
            or item.get("outcome") not in {"passed", "failed", "skipped"} for item in outcomes):
        raise E2EError("Run command must produce check outcome objects")
    ok = code == 0 and (bool(selected) if collect else bool(results and results["passed"] and outcomes)
                       and not results["failed"] and not results["skipped"]
                       and all(item["outcome"] == "passed" for item in outcomes))
    receipt = {"phase": name, "platform": platform, "source": source(repo), "app": app,
               "device": target, "appium_log": policy.get("_appium_log"),
               "selectors": selectors, "exit_code": code, "ok": ok, "collected": selected,
               "results": results, "fresh_install": fresh,
               "fresh_install_receipt": {"application_id": context["application_id"], "device_id": context["device_id"],
                    "artifact_digest": (app or {}).get("artifact_digest")} if fresh and not collect else None,
               "duration_seconds": round(time.monotonic() - started, 2), "log": str(log), "junit": str(junit),
               "log_digest": digest(log), "junit_digest": digest(junit) if junit.exists() else None,
               "collection": str(collection_path) if collect else None,
               "collection_digest": digest(collection_path) if collection_path.exists() else None,
               "metadata_path": context["collection_metadata"] if collect and Path(context["collection_metadata"]).exists() else None,
               "metadata_digest": digest(Path(context["collection_metadata"])) if collect and Path(context["collection_metadata"]).exists() else None,
               "results_path": str(outcomes_path) if outcomes_path.exists() else None,
               "results_digest": digest(outcomes_path) if outcomes_path.exists() else None,
               "outcomes": outcomes}
    file = folder / f"{platform}-{name}.json"
    write_json(file, receipt)
    receipt["path"] = str(file)
    if diagnostic_path.exists():
        diagnostic = read_json(diagnostic_path)
        if (isinstance(diagnostic, dict) and diagnostic.get("origin") == "execution_recipe"
                and isinstance(diagnostic.get("details"), str) and diagnostic["details"]):
            raise E2EPlanError(f"{diagnostic['details']} Evidence: {file}; log: {log}")
        raise E2EError(f"Invalid execution diagnostic; see {diagnostic_path}")
    return receipt


def finding_id(finding):
    return hashlib.sha256(json.dumps(finding, sort_keys=True).encode()).hexdigest()


def failed_test(receipt, node, *, actual_execution=False):
    junit_failure = any(
        item.get("test", "").rsplit("::", 1)[-1] == node.rsplit("::", 1)[-1]
        for item in (receipt.get("results") or {}).get("failed", []))
    outcomes = receipt.get("outcomes", [])
    return junit_failure and (not outcomes and not actual_execution or any(
        item.get("nodeid") == node and item.get("outcome") == "failed"
        and (not actual_execution or item.get("stage", "call") == "call") for item in outcomes))


def validate_receipts(verdict):
    for receipt in verdict.get("receipts", []):
        original = read_json(Path(receipt["path"]))
        if any(original.get(key) != receipt.get(key) for key in original):
            raise E2EError("Receipt does not match verification verdict")
        if receipt["log_digest"] != digest(Path(receipt["log"])):
            raise E2EError("Run log changed after verification")
        if receipt["junit_digest"] and receipt["junit_digest"] != digest(Path(receipt["junit"])):
            raise E2EError("JUnit evidence changed after verification")
        if receipt.get("collection"):
            if (receipt.get("collection_digest") != digest(Path(receipt["collection"]))
                    or receipt.get("collected") != read_json(Path(receipt["collection"]))):
                raise E2EError("Collection evidence changed after verification")
        if receipt.get("eligibility_path"):
            if (receipt.get("eligibility_digest") != digest(Path(receipt["eligibility_path"]))
                    or receipt.get("eligibility") != read_json(Path(receipt["eligibility_path"]))):
                raise E2EError("Active coverage evidence changed after verification")
        if receipt.get("metadata_path") and receipt.get("metadata_digest") != digest(Path(receipt["metadata_path"])):
            raise E2EError("Collection metadata changed after verification")
        if receipt.get("results_path"):
            if (receipt.get("results_digest") != digest(Path(receipt["results_path"]))
                    or receipt.get("outcomes") != read_json(Path(receipt["results_path"]))):
                raise E2EError("Check outcome evidence changed after verification")
        if receipt.get("results") is not None:
            results = junit_results(Path(receipt["junit"]))
            if results != receipt["results"]:
                raise E2EError("Recorded test outcomes differ from JUnit evidence")
            if receipt["ok"] and (receipt["exit_code"] != 0 or not results["passed"] or results["failed"] or results["skipped"]):
                raise E2EError("A passing receipt needs actual successful tests without skips")
        if not receipt["phase"].startswith("baseline") and receipt["source"] != verdict["source"]:
            raise E2EError("Receipt test source differs from the current task")


def baseline_findings(verdict, strategy):
    """Only actual test failures on both revisions qualify for an operator exception."""
    receipts = {item.get("path"): item for item in verdict.get("receipts", [])}
    eligible = []
    for finding in verdict.get("classifications", []):
        if finding.get("kind") != "baseline_or_environment_failure" or not finding.get("test"):
            continue
        task = receipts.get(finding.get("evidence"), {})
        baseline = receipts.get(finding.get("baseline_evidence"), {})
        if all(item.get("exit_code") == 1 and not item.get("ok") and item.get("results")
               and failed_test(item, finding["test"], actual_execution=True) and (item.get("app") or {}).get("artifact_digest")
               and item.get("platform") == finding.get("platform") for item in (task, baseline)) and (
            task.get("app") == baseline.get("app")
            and task.get("source") == verdict.get("source")
            and baseline.get("source", {}).get("sha") == strategy["e2e"]["baseline_sha"]
        ):
            eligible.append(finding)
    return eligible


def validate_binding(task_root, verdict, work_item_id, *, allow_documentation_changes=False):
    if verdict.get("work_item_id") != work_item_id:
        raise E2EError("E2E evidence is stale or belongs to another work item")
    validate_source(task_root / "repo", verdict.get("source"), allow_documentation_changes=allow_documentation_changes)
    if verdict.get("contract_version") != CONTRACT_VERSION:
        raise E2EError("Legacy e2e evidence requires a fresh verification strategy and gate")
    if verdict.get("strategy_digest") != digest(task_root / "spec/verification-strategy.json"):
        raise E2EError("E2E execution strategy changed after verification")
    if verdict.get("support_digests") != support_digests(task_root, read_json(task_root / "spec/verification-strategy.json")):
        raise E2EError("E2E execution support files changed after verification")


def accepted_baseline_findings(task_root, work_item_id, strategy, *, allow_documentation_changes=False):
    path = task_root / "spec/e2e-operator-decisions.json"
    if not path.exists():
        return [], []
    record = read_json(path)
    if record.get("work_item_id") != work_item_id:
        return [], []
    findings = []
    for decision in record.get("decisions", []):
        evidence = Path(decision["verdict_path"])
        if digest(evidence) != decision["verdict_digest"]:
            raise E2EError("Accepted baseline evidence changed after the operator decision")
        verdict = read_json(evidence)
        validate_binding(task_root, verdict, work_item_id, allow_documentation_changes=allow_documentation_changes)
        validate_receipts(verdict)
        eligible = {finding_id(item): item for item in baseline_findings(verdict, strategy)}
        if not decision.get("finding_ids") or set(decision["finding_ids"]) - eligible.keys():
            raise E2EError("Operator exception must identify actual baseline test failures")
        for identifier in decision["finding_ids"]:
            finding = dict(eligible[identifier], operator_event_id=decision["event_id"],
                           operator_comment=decision.get("comment", ""))
            findings.append(finding)
    return record.get("decisions", []), findings


def verify(task_key, task_root, strategy, machine):
    repo = task_root / "repo"
    folder = task_root / "tmp/e2e" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    verdict = {"task_key": task_key, "work_item_id": strategy.get("work_item_id"), "source": source(repo), "contract_version": CONTRACT_VERSION,
               "result": "blocked", "receipts": [], "classifications": [], "report_path": str(folder / "report.md")}
    policy = dict(strategy["e2e"]["policy"])
    policy["_deadline"] = time.monotonic() + policy["run_timeout_seconds"]
    baseline = folder / "baseline"
    lock_root = Path(os.environ.get("E2E_DEVICE_LOCK_ROOT", str(task_root.parent / ".locks/e2e")))
    lock_root.mkdir(parents=True, exist_ok=True)
    try:
        health = doctor(machine)
        if not health["ok"]:
            raise E2EError("; ".join(health["errors"]))
        if verdict["source"]["dirty"]:
            raise E2EError("Commit the task changes before e2e verification")
        verdict["strategy_digest"] = digest(task_root / "spec/verification-strategy.json")
        verdict["support_digests"] = support_digests(task_root, strategy)
        platform_configs = configurations(strategy)
        policy["_configurations"] = platform_configs
        policy["_task_root"] = task_root
        decisions, accepted = accepted_baseline_findings(task_root, strategy.get("work_item_id"), strategy)
        verdict["operator_decisions"] = decisions
        verdict["accepted_findings"] = accepted
        verdict["scope"] = {}
        if not isinstance(strategy["e2e"].get("baseline_sha"), str) or not strategy["e2e"]["baseline_sha"]:
            raise E2EError("Snapshot must fetch origin/master before verification")
        for platform in ("ios", "android"):
            if platform not in platform_configs:
                continue
            config = platform_configs[platform]
            with ExitStack() as device_scope:
                selected_machine = machine
                if platform == "ios" and machine.ios_pool:
                    selected_machine = device_scope.enter_context(reserve_ios(machine, lock_root, policy["_deadline"]))
                else:
                    lock = device_scope.enter_context((lock_root / f"{platform}-device.lock").open("w"))
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise E2EError(f"Reserved {platform} device is busy; retry verification when it is free")
                target = device(selected_machine, platform)
                collected = phase(selected_machine, repo, platform, target, None, policy, folder, "collection", config["collection"], collect=True)
                verdict["receipts"].append(collected)
                if not collected["ok"]:
                    if not baseline.exists():
                        git(repo, "worktree", "add", "--detach", str(baseline), strategy["e2e"]["baseline_sha"])
                    reference = phase(selected_machine, baseline, platform, target, None, policy, folder, "baseline-collection", config["collection"], collect=True)
                    verdict["receipts"].append(reference)
                    verdict["result"] = "failed" if reference["ok"] else "blocked"
                    verdict["details"] = f"{platform} collection failed; see {collected['log']} and {reference['log']}"
                    break
                removed = config.get("removed_tests", [])
                if any(any(item == node or item.startswith(node + "[") for item in collected["collected"]) for node in removed):
                    verdict["result"] = "failed"
                    verdict["details"] = "A removed test is still collected"
                    break
                if config.get("collection_only"):
                    continue
                exceptions = [item for item in accepted if item["platform"] == platform]
                accepted_apps = [receipt["app"] for item in exceptions for decision in decisions
                                 for receipt in read_json(Path(decision["verdict_path"]))["receipts"]
                                 if receipt["path"] == item["evidence"]]
                # A continuation keeps the build the operator reviewed, even if
                # a newer master artifact has appeared in the shared build store.
                app = pin_app(task_root, selected_machine, platform,
                    resolve_app(selected_machine, platform, accepted_apps[0] if accepted_apps else config.get("app")))
                selectors = selection(config, platform, policy, repo)
                picked = phase(selected_machine, repo, platform, target, app, policy, folder, "selection", selectors, collect=True)
                verdict["receipts"].append(picked)
                if not picked["ok"]:
                    raise E2EPlanError("Selected test count is zero or invalid")
                selected = picked["collected"]
                if "eligibility" in config["commands"]:
                    checked = check_selection(selected_machine, repo, platform, target, app, policy, folder, selected)
                    verdict["receipts"].append(checked)
                    selected = checked["collected"]
                    verdict.setdefault("selection_exclusions", {})[platform] = [
                        item for item in checked["eligibility"]["checks"] if not item["eligible"]]
                    selectors = selected
                if not selected or len(selected) > policy["max_tests"]:
                    raise E2EPlanError("No active checks selected, or active check count exceeds the configured limit")
                excluded = {item["test"] for item in exceptions}
                if excluded - set(selected):
                    raise E2EError("Accepted scenario no longer belongs to the selected test scope")
                for accepted_app in accepted_apps:
                    if accepted_app != app:
                        raise E2EError("App build changed after the operator decision; run a new verification gate")
                verdict["scope"][platform] = {"selected": selected, "accepted": sorted(excluded)}
                if excluded:
                    selectors = [node for node in selected if node not in excluded]
                    if not selectors:
                        continue
                policy["_appium_log"] = str(lock_root / f"appium-{machine.appium_port}.log")
                with (lock_root / f"appium-{machine.appium_port}.lock").open("w") as server_lock:
                    fcntl.flock(server_lock, fcntl.LOCK_EX)
                    ensure_server(machine, Path(policy["_appium_log"]))
                if platform == "android":
                    # Register before boot so partially failed starts are also cleaned up.
                    # ExitStack runs this before releasing the device lock.
                    device_scope.callback(finish_android, machine, verdict)
                elif machine.ios_pool:
                    device_scope.callback(finish_ios, selected_machine, verdict)
                target = device(selected_machine, platform, boot=True)
                install(selected_machine, platform, app, target)
                run = phase(selected_machine, repo, platform, target, app, policy, folder, "run", selectors, fresh=policy["fresh_install"])
                verdict["receipts"].append(run)
                latest = run
                failed_nodes = [item["nodeid"] for item in run["outcomes"] if item["outcome"] == "failed"]
                if not run["ok"] and run["exit_code"] == 1:
                    for attempt in range(policy["failure_reruns"]):
                        latest = phase(selected_machine, repo, platform, target, app, policy, folder, f"rerun-{attempt + 1}", failed_nodes or selectors, fresh=True)
                        verdict["receipts"].append(latest)
                        if latest["ok"]:
                            break
                if latest["ok"]:
                    if not run["ok"]:
                        verdict["classifications"].append({"platform": platform, "kind": "flaky", "evidence": latest["path"]})
                    repeat = phase(selected_machine, repo, platform, target, app, policy, folder, "fresh-run", selectors, fresh=True)
                    verdict["receipts"].append(repeat)
                    if not repeat["ok"]:
                        latest = repeat
                        failed_nodes = [item["nodeid"] for item in repeat["outcomes"] if item["outcome"] != "passed"]
                        seen = {item["nodeid"] for item in repeat["outcomes"]}
                        failed_nodes += [node for node in selected if node not in excluded and node not in seen]
                        if repeat["exit_code"] == 1:
                            for attempt in range(policy["failure_reruns"]):
                                latest = phase(selected_machine, repo, platform, target, app, policy, folder,
                                               f"fresh-run-rerun-{attempt + 1}", list(dict.fromkeys(failed_nodes)) or selectors, fresh=True)
                                verdict["receipts"].append(latest)
                                if latest["ok"]:
                                    verdict["classifications"].append({"platform": platform, "kind": "flaky",
                                                                        "evidence": repeat["path"], "rerun_evidence": latest["path"]})
                                    break
                        if latest["ok"]:
                            continue
                    else:
                        continue
                if latest["exit_code"] != 1:
                    raise E2EError(f"{platform} runner failed before a valid test verdict; see {latest['log']}")
                if not baseline.exists():
                    git(repo, "worktree", "add", "--detach", str(baseline), strategy["e2e"]["baseline_sha"])
                regressions = False
                remaining = [item["nodeid"] for item in latest["outcomes"] if item["outcome"] == "failed"]
                for index, node in enumerate(list(dict.fromkeys(remaining)) or failed_nodes or selectors):
                    reference = phase(selected_machine, baseline, platform, target, app, policy, folder,
                                      f"baseline-{index + 1}", [node], fresh=True)
                    verdict["receipts"].append(reference)
                    kind = "test_regression" if reference["ok"] else (
                        "baseline_or_environment_failure" if failed_test(latest, node, actual_execution=True)
                        and failed_test(reference, node, actual_execution=True) else "environment_failure")
                    regressions = regressions or reference["ok"]
                    verdict["classifications"].append({"platform": platform, "test": node, "kind": kind,
                                                        "evidence": latest["path"], "baseline_evidence": reference["path"]})
                verdict["result"] = "failed" if regressions else "blocked"
                break
        else:
            verdict["result"] = "accepted_with_warnings" if accepted else "passed"
    except (E2EError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        if isinstance(exc, E2EPlanError):
            verdict["failure_origin"] = "execution_recipe"
        verdict["details"] = str(exc)
    finally:
        if baseline.exists():
            try:
                git(repo, "worktree", "remove", "--force", str(baseline))
            except E2EError as exc:
                verdict.setdefault("cleanup_warnings", []).append(str(exc))
        report = [f"# E2E verification for {task_key}", "", f"Result: {verdict['result']}",
                  f"Test source: {verdict['source']['sha']}", "", verdict.get("details", ""), "",
                  "| Platform | Check | App SHA | Result | Evidence |", "|---|---|---|---|---|"]
        for receipt in verdict["receipts"]:
            report.append(f"| {receipt['platform']} | {receipt['phase']} | {(receipt['app'] or {}).get('sha', '-')} | {'passed' if receipt['ok'] else 'failed'} | {receipt['path']} |")
        if verdict.get("cleanup_warnings"):
            report += ["", "## Cleanup warnings", ""] + [f"- {warning}" for warning in verdict["cleanup_warnings"]]
        if "android_emulator_stopped" in verdict:
            report += ["", f"Android emulator stopped: {verdict['android_emulator_stopped']}"]
        for cleanup in verdict.get("ios_simulator_cleanup", []):
            report += ["", f"iOS simulator {cleanup['udid']} stopped: {cleanup['stopped']}"]
        if verdict["classifications"]:
            report += ["", "## Failure analysis", ""]
            for finding in verdict["classifications"]:
                report.append(f"- {finding['platform']}: {finding['kind']}; {finding.get('test', 'selected scenarios')}; evidence: {finding['evidence']}")
                if finding.get("baseline_evidence"):
                    report.append(f"  Baseline evidence: {finding['baseline_evidence']}")
        if any(verdict.get("selection_exclusions", {}).values()):
            report += ["", "## Candidates outside active coverage", ""]
            for platform, exclusions in verdict["selection_exclusions"].items():
                for item in exclusions:
                    report.append(f"- {platform}: {item['nodeid']}; {item['reason']}")
        if verdict.get("accepted_findings"):
            report += ["", "## Baseline failures accepted by the operator", "",
                       "These scenarios did not pass. The operator accepted them for this gate only; all other selected checks remain required.", ""]
            for finding in verdict["accepted_findings"]:
                report += [f"- {finding['platform']}: {finding['test']}; operator event {finding['operator_event_id']}",
                           f"  Task evidence: {finding['evidence']}; baseline evidence: {finding['baseline_evidence']}",
                           f"  Comment: {finding['operator_comment'] or '(no comment)'}"]
                original = next(read_json(Path(decision["verdict_path"])) for decision in verdict["operator_decisions"]
                                if decision["event_id"] == finding["operator_event_id"])
                report += ["", describe_verdict(dict(original, classifications=[finding], accepted_findings=[]))["details"], ""]
        Path(verdict["report_path"]).write_text("\n".join(report) + "\n")
        write_json(folder / "verdict.json", verdict)
        write_json(task_root / "spec/e2e-verdict.json", verdict)
    return verdict


def describe_verdict(verdict):
    """Explain the gate using receipt errors, without exposing serialized internal records."""
    result = verdict.get("result")
    findings = [item for item in verdict.get("classifications", [])
                if item.get("kind") in {"baseline_or_environment_failure", "test_regression", "environment_failure"}]
    summary = {
        "passed": "E2E verification passed",
        "accepted_with_warnings": "E2E verification accepted with warnings",
        "failed": "E2E verification failed",
        "blocked": "E2E verification needs environment recovery",
    }.get(result, "E2E verification is blocked")
    if result == "blocked" and any(item["kind"] == "baseline_or_environment_failure" for item in findings):
        summary = "A selected test also fails on baseline"
    elif result == "blocked" and verdict.get("failure_origin") == "execution_recipe":
        summary = "E2E execution strategy needs correction"
    receipts = {item.get("path"): item for item in verdict.get("receipts", [])}
    paragraphs = [verdict["details"]] if verdict.get("details") else []
    for finding in findings:
        platform = {"ios": "iOS", "android": "Android"}.get(finding.get("platform"), "Mobile")
        node = finding.get("test", "Selected scenario")
        if finding["kind"] == "baseline_or_environment_failure":
            explanation = "fails on the task branch and on baseline using the same app build. A task-specific regression has not been established."
        elif finding["kind"] == "test_regression":
            explanation = "fails on the task branch but passes on baseline using the same app build. Test corrections are required."
        else:
            explanation = "could not execute because setup, cleanup or the runner environment failed. These failures cannot be accepted as baseline test findings."
        lines = [f"{platform}: {node}\nThis scenario {explanation}"]
        for label, key in (("Task failure", "evidence"), ("Baseline failure", "baseline_evidence")):
            receipt = receipts.get(finding.get(key), {})
            errors = [item.get("details", "") for item in receipt.get("outcomes", [])
                      if item.get("outcome") == "failed" and item.get("nodeid") == node]
            if not errors:
                errors = [item.get("details", "") for item in (receipt.get("results") or {}).get("failed", [])
                          if item.get("test", "").rsplit("::", 1)[-1] == node.rsplit("::", 1)[-1]]
            for error in errors:
                match = re.search(r"^\s*E\s+(.+)$", error, re.MULTILINE)
                if match:
                    lines.append(f"{label}: {match[1].strip()[:300]}")
                    break
        paragraphs.append("\n".join(lines))
    for finding in verdict.get("accepted_findings", []):
        paragraphs.append(f"{finding['platform']}: {finding['test']}\nBaseline failure accepted by the operator for this gate only. Comment: {finding.get('operator_comment') or '(no comment)'}")
    return {"summary": summary, "details": "\n\n".join(paragraphs) or verdict.get("details") or "See the verification report for individual test results."}


def bound_selection(receipts, platform, picked, config, policy):
    if "eligibility" not in config["commands"]:
        return picked["collected"]
    checks = [item for item in receipts if item["platform"] == platform and item["phase"] == "eligibility"]
    if (len(checks) != 1 or not checks[0].get("ok") or checks[0].get("exit_code") != 0
            or checks[0].get("selectors") != picked["collected"]
            or checks[0].get("app") != picked.get("app")
            or not checks[0].get("eligibility_path")):
        raise E2EError("Missing bound active coverage selection")
    active = eligible_checks(checks[0].get("eligibility"), picked["collected"], config, policy)
    if checks[0].get("collected") != active or not active or len(active) > policy["max_tests"]:
        raise E2EError("Active coverage differs from the execution selection")
    return active


def validate_verdict(task_root, work_item_id, *, allow_documentation_changes=False):
    verdict = read_json(task_root / "spec/e2e-verdict.json")
    if verdict.get("work_item_id") != work_item_id:
        raise E2EError("E2E evidence is stale or belongs to another work item")
    validate_source(task_root / "repo", verdict.get("source"), allow_documentation_changes=allow_documentation_changes)
    if verdict.get("result") not in {"passed", "accepted_with_warnings"}:
        return verdict
    validate_binding(task_root, verdict, work_item_id, allow_documentation_changes=allow_documentation_changes)
    strategy = read_json(task_root / "spec/verification-strategy.json")
    decisions, accepted = accepted_baseline_findings(
        task_root, work_item_id, strategy, allow_documentation_changes=allow_documentation_changes)
    if verdict.get("result") == "accepted_with_warnings":
        if not accepted or verdict.get("operator_decisions") != decisions or verdict.get("accepted_findings") != accepted:
            raise E2EError("Accepted verification requires matching operator decisions")
    elif accepted:
        raise E2EError("Accepted baseline failures must remain visible as warnings")
    receipts = verdict.get("receipts", [])
    runs = [item for item in receipts if item["phase"] == "run"]
    if not runs and not accepted:
        raise E2EError("E2E success requires actual test runs")
    platform_configs = configurations(strategy)
    expected_runs = {platform for platform, value in platform_configs.items() if not value.get("collection_only")}
    active_scopes = {}
    for platform in expected_runs:
        picked = next((item for item in receipts if item["platform"] == platform and item["phase"] == "selection" and item["ok"]), None)
        if picked is None or picked["selectors"] != selection(platform_configs[platform], platform, strategy["e2e"]["policy"]):
            raise E2EError("Missing bound check selection")
        active_scopes[platform] = bound_selection(receipts, platform, picked, platform_configs[platform], strategy["e2e"]["policy"])
    for platform in list(expected_runs):
        exceptions = {item["test"] for item in accepted if item["platform"] == platform}
        if not exceptions:
            continue
        picked = next((item for item in receipts if item["platform"] == platform and item["phase"] == "selection" and item["ok"]), None)
        if picked is None or picked["selectors"] != selection(platform_configs[platform], platform, strategy["e2e"]["policy"]):
            raise E2EError("Missing original test selection for accepted verification")
        for finding in (item for item in accepted if item["platform"] == platform):
            original = next(receipt for decision in decisions
                            for receipt in read_json(Path(decision["verdict_path"]))["receipts"]
                            if receipt["path"] == finding["evidence"])
            if picked.get("app") != original.get("app"):
                raise E2EError("Accepted verification must retain the original app build")
        selected = set(active_scopes[platform])
        if not selected or exceptions - selected:
            raise E2EError("Accepted findings differ from the selected scenarios")
        remaining = selected - exceptions
        run = next((item for item in runs if item["platform"] == platform), None)
        if remaining:
            if run is None or set(run["selectors"]) != remaining:
                raise E2EError("All scenarios outside the operator exception must be run")
        else:
            expected_runs.remove(platform)
    if {item["platform"] for item in runs} != expected_runs:
        raise E2EError("Not all planned platforms were run")
    for platform in platform_configs:
        if not any(item["platform"] == platform and item["phase"] == "collection" and item["ok"] for item in receipts):
            raise E2EError("Missing successful platform collection")
    for run in runs:
        picked = next((item for item in receipts if item["platform"] == run["platform"] and item["phase"] == "selection"), None)
        if accepted and (picked is None or run.get("app") != picked.get("app")):
            raise E2EError("Continued verification must retain the selected app build")
        if not run.get("app") or not run["app"].get("artifact_digest"):
            raise E2EError("An actual run needs an identified app artifact")
        expected_nodes = set(active_scopes[run["platform"]]) - {finding["test"] for finding in accepted if finding["platform"] == run["platform"]}
        if {item["nodeid"] for item in run.get("outcomes", [])} != expected_nodes:
            raise E2EError("Actual execution differs from the selected checks")
        if not run["ok"] and not any(
            item["platform"] == run["platform"] and item["phase"].startswith("rerun-")
            and item["ok"] and item.get("app") == run["app"] for item in receipts
        ):
            raise E2EError("Initial test failures have no passing retry")
        validate_fresh_coverage(receipts, run, expected_nodes, strategy["e2e"]["policy"]["failure_reruns"])
    validate_receipts(verdict)
    return verdict


def validate_fresh_coverage(receipts, run, expected_nodes, max_reruns):
    attempts = [item for item in receipts if item["platform"] == run["platform"]
                and (item["phase"] == "fresh-run" or item["phase"].startswith("fresh-run-rerun-"))]
    if (not attempts or attempts[0]["phase"] != "fresh-run"
            or attempts[0].get("selectors") != run.get("selectors") or len(attempts) > max_reruns + 1):
        raise E2EError("Missing full fresh-install selection or invalid retry sequence")
    states = {}
    for index, receipt in enumerate(attempts):
        expected_phase = "fresh-run" if index == 0 else f"fresh-run-rerun-{index}"
        if (receipt["phase"] != expected_phase or not receipt.get("fresh_install")
                or receipt.get("app") != run.get("app") or receipt.get("device") != run.get("device")
                or receipt.get("exit_code") not in {0, 1}):
            raise E2EError("Fresh execution changed the app/device or lacks valid completion")
        installation = receipt.get("fresh_install_receipt") or {}
        if not installation.get("application_id") or installation.get("artifact_digest") != run["app"]["artifact_digest"]:
            raise E2EError("Fresh installation has no matching app receipt")
        device_id = receipt["device"].get("udid", receipt["device"].get("serial"))
        if "device_id" in installation and installation["device_id"] != device_id:
            raise E2EError("Fresh installation receipt names a different device")
        grouped = {}
        for outcome in receipt.get("outcomes", []):
            grouped.setdefault(outcome["nodeid"], []).append(outcome["outcome"])
        if not grouped or set(grouped) - expected_nodes:
            raise E2EError("Fresh execution differs from the selected checks")
        if index and receipt.get("selectors") != run.get("selectors"):
            # Retain support for earlier complete-selection retries.
            if set(receipt["selectors"]) != set(grouped):
                raise E2EError("Fresh retry outcomes differ from its addressed checks")
        if receipt["ok"] and any(status != "passed" for statuses in grouped.values() for status in statuses):
            raise E2EError("Passing fresh receipt contains failed or skipped checks")
        states.update({node: all(status == "passed" for status in statuses) for node, statuses in grouped.items()})
    if not attempts[-1]["ok"] or set(states) != expected_nodes or not all(states.values()):
        raise E2EError("Fresh installation has no passing evidence for every selected check")


def mr_description(task_key, task_root):
    recorded = read_json(task_root / "spec/e2e-verdict.json")
    verdict = validate_verdict(task_root, recorded.get("work_item_id"), allow_documentation_changes=True)
    if verdict["result"] not in {"passed", "accepted_with_warnings"}:
        raise E2EError("An e2e MR requires passing or explicitly accepted verification")
    jira_base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    changes = git(task_root / "repo", "log", "--format=%s", "origin/master..HEAD")
    lines = [f"Jira: {jira_base + '/' + task_key if jira_base else task_key}", "", changes, "",
             f"Verified test source: `{verdict['source']['sha']}`", ""]
    delivery_sha = git(task_root / "repo", "rev-parse", "HEAD")
    if verdict["source"]["sha"] != delivery_sha:
        documentation = validate_source(task_root / "repo", verdict["source"], allow_documentation_changes=True)
        lines += [f"Delivery source: `{delivery_sha}`",
                  "Post-verification changes: " + (", ".join(f"`{name}`" for name in documentation) or "no file changes") + ".",
                  "Original verification evidence retained; no additional test run was performed.", ""]
    lines += [f"Verification result: {verdict['result']}", "",
              "| Platform | Check | App SHA | Passed / Failed / Skipped |", "|---|---|---|---|"]
    for receipt in verdict["receipts"]:
        if receipt["results"] is not None:
            counts = receipt["results"]
            lines.append(f"| {receipt['platform']} | {receipt['phase']} | `{(receipt['app'] or {}).get('sha', '-')}` | {len(counts['passed'])} / {len(counts['failed'])} / {len(counts['skipped'])} |")
    if verdict["classifications"]:
        lines += ["", "Observed failures: " + "; ".join(f"{item['platform']}: {item['kind']}" for item in verdict["classifications"])]
    if verdict.get("accepted_findings"):
        lines += ["", "Baseline failures accepted by the operator (these tests did not pass):"]
        for item in verdict["accepted_findings"]:
            lines.append(f"- {item['platform']}: {item['test']}; operator event {item['operator_event_id']}; {item.get('operator_comment') or '(no comment)'}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("doctor", "verify", "mr-description", "syntax"))
    parser.add_argument("task_key", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            machine = Machine.from_env()
            result = doctor(machine)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if not args.task_key or not re.fullmatch(r"QA-\d+", args.task_key):
            raise E2EError("verify requires a QA task key")
        task_root = Path(os.environ["SDD_WORKDIR"]) / args.task_key
        if args.command == "mr-description":
            print(mr_description(args.task_key, task_root))
            return 0
        if args.command == "syntax":
            files = git(task_root / "repo", "ls-files", "*.py").splitlines()
            for name in files:
                path = task_root / "repo" / name
                if path.exists():
                    ast.parse(path.read_text(), filename=name)
            print(json.dumps({"result": "passed", "python_files": len(files)}))
            return 0
        machine = Machine.from_env()
        strategy = read_json(task_root / "spec/verification-strategy.json")
        def interrupted(signum, frame):
            raise E2EError(f"E2E verification interrupted by signal {signum}")
        handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            result = verify(args.task_key, task_root, strategy, machine)
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
        print(json.dumps(result, indent=2))
        return {"passed": 0, "accepted_with_warnings": 0, "failed": 1, "blocked": 2}[result["result"]]
    except (E2EError, OSError, ValueError, KeyError, SyntaxError) as exc:
        if args.command == "mr-description":
            print(f"Cannot prepare QA merge request: {exc}", file=sys.stderr)
        else:
            print(json.dumps({"result": "blocked", "details": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
