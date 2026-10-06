"""Optional pytest evidence/fresh-install protocol, independent of the test project."""

import os
import json
import subprocess
from functools import wraps

import pytest

_reports = []


def pytest_configure(config):
    """Apply only generic Appium resources assigned by the factory's device lease."""
    raw = os.environ.get("FACTORY_E2E_APPIUM_CAPABILITIES")
    if not raw:
        return
    try:
        assigned = json.loads(raw)
        from appium.webdriver.webdriver import WebDriver
    except (ValueError, ImportError) as exc:
        raise pytest.UsageError(f"Cannot apply assigned Appium device capabilities: {exc}") from exc
    if not isinstance(assigned, dict):
        raise pytest.UsageError("Assigned Appium device capabilities must be an object")
    original = WebDriver.start_session

    @wraps(original)
    def start_session(self, capabilities, *args, **kwargs):
        current = capabilities if isinstance(capabilities, dict) else capabilities.to_capabilities()
        # A test recipe cannot redirect a leased session to another user's device.
        return original(self, {**current, **assigned}, *args, **kwargs)

    WebDriver.start_session = start_session
    config.add_cleanup(lambda: setattr(WebDriver, "start_session", original))


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
