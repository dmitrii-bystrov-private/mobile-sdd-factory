"""Separate operator policy from machine-specific paths and devices."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil


class E2EError(RuntimeError):
    pass


DEFAULTS = {
    "include_smoke": True,
    "fresh_install": True,
    "max_tests": 10,
    "run_timeout_seconds": 1800,
    "test_timeout_seconds": 600,
    "failure_reruns": 1,
}


def normalize_defaults(value: object) -> dict:
    result = dict(DEFAULTS)
    if value is None:
        return result
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Invalid e2e settings")
    for name, raw in value.items():
        if type(DEFAULTS[name]) is bool:
            if type(raw) is not bool:
                raise ValueError(f"{name} must be a boolean")
        elif type(raw) is not int or raw < (0 if name == "failure_reruns" else 1):
            raise ValueError(f"{name} must be a positive integer")
        result[name] = raw
    return result


@dataclass(frozen=True)
class Machine:
    repo: Path
    python: Path
    build_root: Path | None
    ios_udid: str
    android_avd: str
    android_serial: str
    android_sdk: Path
    appium: str
    appium_port: int

    @classmethod
    def from_env(cls):
        repo = Path(os.environ.get("E2E_DIR", "")).expanduser()
        if not os.environ.get("E2E_DIR"):
            raise E2EError("Set E2E_DIR to the e2e project checkout")
        if not os.environ.get("E2E_PYTHON"):
            raise E2EError("Set E2E_PYTHON to the verification Python executable in ~/.zshrc")
        return cls(
            repo=repo,
            python=Path(os.environ["E2E_PYTHON"]).expanduser(),
            build_root=Path(os.environ["E2E_BUILD_ROOT"]).expanduser() if os.environ.get("E2E_BUILD_ROOT") else None,
            ios_udid=os.environ.get("E2E_IOS_SIMULATOR_UDID", ""),
            android_avd=os.environ.get("E2E_ANDROID_AVD", ""),
            android_serial=os.environ.get("E2E_ANDROID_SERIAL", "emulator-5584"),
            android_sdk=Path(os.environ.get("ANDROID_HOME", "~/Library/Android/sdk")).expanduser(),
            appium=os.environ.get("E2E_APPIUM_BIN") or shutil.which("appium") or "appium",
            appium_port=int(os.environ.get("E2E_APPIUM_PORT", "4743")),
        )
