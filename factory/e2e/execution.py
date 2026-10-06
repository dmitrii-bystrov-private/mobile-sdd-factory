"""Task-provided execution recipes; no repository layout or project imports."""

import hashlib
from pathlib import Path

from factory.e2e.config import E2EError


CONTRACT_VERSION = 2


class E2EPlanError(E2EError):
    """The routed execution strategy needs correction."""


def identifiers(value, label, *, required=False):
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value)
            or (required and not value)):
        raise E2EPlanError(f"{label} must contain nonempty check identifiers")
    return list(dict.fromkeys(value))


def configurations(strategy):
    e2e = strategy.get("e2e", {})
    if not isinstance(e2e, dict):
        raise E2EPlanError("verification-strategy.json e2e must be an object")
    platforms = e2e.get("platforms")
    if not isinstance(platforms, dict) or not platforms or set(platforms) - {"ios", "android"}:
        raise E2EPlanError("Complete verification-strategy.json e2e.platforms from the task checkout before verification")
    for platform, config in platforms.items():
        if not isinstance(config, dict):
            raise E2EPlanError(f"Invalid execution recipe for {platform}")
        if "collection_only" in config and type(config["collection_only"]) is not bool:
            raise E2EPlanError("collection_only must be a boolean")
        for name in ("tests", "smoke_tests", "removed_tests"):
            identifiers(config.get(name, []), name)
        identifiers(config.get("collection"), "collection", required=True)
        commands = config.get("commands")
        required = ("collect",) if config.get("collection_only") else ("collect", "run")
        if not isinstance(commands, dict) or any(not isinstance(commands.get(name), list) or not commands[name]
                or any(not isinstance(arg, str) or not arg for arg in commands[name])
                or commands[name].count("{selectors}") != 1 for name in required):
            raise E2EPlanError("Execution commands must be argv arrays with one {selectors} argument")
        env = config.get("environment", {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise E2EPlanError("Execution environment must map names to strings")
        identifiers(config.get("unset_environment", []), "unset_environment")
        requested = config.get("app")
        if requested is not None and (not isinstance(requested, dict) or not isinstance(requested.get("path"), str)
                or not isinstance(requested.get("sha"), str) or not requested["sha"]):
            raise E2EPlanError("An explicit app selection needs path and source SHA strings")
        if platform == "android" and not config.get("collection_only") and (not isinstance(config.get("application_id"), str)
                or not config["application_id"].strip()):
            raise E2EPlanError("Android execution needs application_id from the selected app/project")
    if all(config.get("collection_only") for config in platforms.values()):
        raise E2EPlanError("Verification needs at least one actual device run")
    return platforms


def selection(config, platform, policy, repo=None):
    tests = identifiers(config.get("tests", []), "tests")
    if policy["include_smoke"]:
        tests += identifiers(config.get("smoke_tests"), "smoke_tests", required=True)
    if not tests:
        raise E2EPlanError(f"No runnable checks selected for {platform}")
    return list(dict.fromkeys(tests))


def support_digests(task_root, strategy):
    result = {}
    e2e = strategy.get("e2e", {})
    if not isinstance(e2e, dict):
        raise E2EPlanError("verification-strategy.json e2e must be an object")
    for name in identifiers(e2e.get("support_files", []), "support_files"):
        path = (task_root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(task_root.resolve()):
            raise E2EPlanError("Execution support files must be inside the task snapshot")
        try:
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise E2EPlanError(f"Missing execution support file: {name}") from exc
    return result


def render(text, context):
    # Replace only known tokens; shell/JSON braces remain literal.
    for name, value in context.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def command(config, name, selectors, context):
    argv = []
    for arg in config["commands"][name]:
        if arg == "{selectors}":
            argv.extend(selectors)
        else:
            argv.append(render(arg, context))
    return argv
