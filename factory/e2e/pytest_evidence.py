"""Optional pytest evidence/fresh-install protocol, independent of the test project."""

import os
import json
import subprocess
import inspect
from copy import copy
from functools import wraps
from pathlib import Path

import pytest

_reports = []


def pytest_configure(config):
    """Bind Appium clients to the factory's server and leased device resources."""
    raw = os.environ.get("FACTORY_E2E_APPIUM_CAPABILITIES")
    endpoint = os.environ.get("FACTORY_E2E_APPIUM_URL")
    if not raw and not endpoint:
        return
    try:
        assigned = json.loads(raw) if raw else {}
    except ValueError as exc:
        raise pytest.UsageError(f"Cannot apply assigned Appium device capabilities: {exc}") from exc
    try:
        from appium.webdriver.webdriver import WebDriver
        from urllib3.exceptions import MaxRetryError, NewConnectionError
    except ImportError as exc:
        # The evidence protocol also supports pytest checks without an Appium client.
        if not raw:
            return
        raise pytest.UsageError(f"Cannot apply assigned Appium device capabilities: {exc}") from exc
    if not isinstance(assigned, dict):
        raise pytest.UsageError("Assigned Appium device capabilities must be an object")
    original = WebDriver.start_session

    @wraps(original)
    def start_session(self, capabilities, *args, **kwargs):
        current = capabilities if isinstance(capabilities, dict) else capabilities.to_capabilities()
        expected = os.environ.get("FACTORY_E2E_PLATFORM")
        requested = str(current.get("platformName", "")).lower()
        if expected and requested != expected:
            details = (f"Appium client requested platform {requested or '(missing)'}, but the factory gate "
                       f"selected {expected}. Map the project's platform input in the execution recipe before session creation.")
            diagnostic = os.environ.get("FACTORY_E2E_DIAGNOSTIC")
            if diagnostic:
                Path(diagnostic).write_text(json.dumps({"origin": "execution_recipe", "details": details}) + "\n")
            pytest.exit(details, returncode=2)
        # A test recipe cannot redirect a leased session to another user's device.
        try:
            return original(self, {**current, **assigned}, *args, **kwargs)
        except (MaxRetryError, NewConnectionError) as exc:
            pytest.exit(f"Appium session connection failed at the factory endpoint {endpoint}: {exc}. "
                        "Environment recovery is required; stopping without test retries or baseline runs.", returncode=2)

    WebDriver.start_session = start_session
    config.add_cleanup(lambda: setattr(WebDriver, "start_session", original))
    if endpoint:
        original_init = WebDriver.__init__
        signature = inspect.signature(original_init)

        @wraps(original_init)
        def initialize(self, *args, **kwargs):
            bound = signature.bind(self, *args, **kwargs)
            bound.arguments["command_executor"] = endpoint
            client_config = bound.arguments.get("client_config")
            if client_config is not None:
                client_config = copy(client_config)
                client_config.remote_server_addr = endpoint
                if hasattr(client_config, "direct_connection"):
                    client_config.direct_connection = False
                bound.arguments["client_config"] = client_config
            if "direct_connection" in signature.parameters:
                bound.arguments["direct_connection"] = False
            return original_init(*bound.args, **bound.kwargs)

        WebDriver.__init__ = initialize
        config.add_cleanup(lambda: setattr(WebDriver, "__init__", original_init))


def pytest_runtest_logreport(report):
    if report.failed or report.when == "call":
        _reports.append({"nodeid": report.nodeid, "stage": report.when, "outcome": report.outcome,
                         "details": str(report.longrepr)[-2500:] if report.failed else ""})


def pytest_sessionfinish(session, exitstatus):
    file = os.environ.get("FACTORY_E2E_RESULTS")
    if file:
        with open(file, "w") as handle:
            json.dump(_reports, handle)
    collection = os.environ.get("FACTORY_E2E_COLLECTION")
    if collection and session.config.option.collectonly:
        with open(collection, "w") as handle:
            json.dump([item.nodeid for item in session.items], handle)


@pytest.fixture(autouse=True)
def factory_fresh_app():
    if os.environ.get("FACTORY_E2E_FRESH_INSTALL") == "1":
        if os.environ["FACTORY_E2E_PLATFORM"] == "android":
            adb = [os.environ["FACTORY_E2E_ADB"], "-s", os.environ["FACTORY_E2E_DEVICE_ID"]]
            subprocess.run([*adb, "uninstall", os.environ["FACTORY_E2E_APP_ID"]], capture_output=True, check=True, timeout=60)
            subprocess.run([*adb, "install", "-g", os.environ["FACTORY_E2E_APP"]],
                           capture_output=True, check=True, timeout=180)
        else:
            device = os.environ["FACTORY_E2E_DEVICE_ID"]
            subprocess.run(["xcrun", "simctl", "uninstall", device, os.environ["FACTORY_E2E_APP_ID"]],
                           capture_output=True, check=True, timeout=60)
            subprocess.run(["xcrun", "simctl", "install", device, os.environ["FACTORY_E2E_APP"]],
                           capture_output=True, check=True, timeout=120)
    yield
