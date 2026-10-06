"""Separate operator policy from machine-specific paths and devices."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from uuid import UUID


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
    ios_pool: tuple[str, ...] = ()
    ios_wda_port_base: int = 8110
    ios_mjpeg_port_base: int = 9110
    ios_wda_root: Path | None = None

    @classmethod
    def from_env(cls):
        repo = Path(os.environ.get("E2E_DIR", "")).expanduser()
        if not os.environ.get("E2E_DIR"):
            raise E2EError("Set E2E_DIR to the e2e project checkout")
        if not os.environ.get("E2E_PYTHON"):
            raise E2EError("Set E2E_PYTHON to the verification Python executable in ~/.zshrc")
        pool = ()
        if "SDD_E2E_IOS_SIMULATOR_UDIDS" in os.environ:
            try:
                pool = tuple(str(UUID(value.strip())).upper() for value in
                             os.environ["SDD_E2E_IOS_SIMULATOR_UDIDS"].split(","))
            except ValueError as exc:
                raise E2EError("SDD_E2E_IOS_SIMULATOR_UDIDS must contain comma-separated simulator UUIDs") from exc
            if len(set(pool)) != len(pool):
                raise E2EError("SDD_E2E_IOS_SIMULATOR_UDIDS contains duplicate devices")
            for name in ("SDD_E2E_IOS_WDA_PORT_BASE", "SDD_E2E_IOS_MJPEG_PORT_BASE", "SDD_E2E_IOS_WDA_ROOT"):
                if not os.environ.get(name):
                    raise E2EError(f"Set {name} in ~/.zshrc for the dedicated iOS pool")
        try:
            wda = int(os.environ.get("SDD_E2E_IOS_WDA_PORT_BASE", "8110"))
            mjpeg = int(os.environ.get("SDD_E2E_IOS_MJPEG_PORT_BASE", "9110"))
            appium_port = int(os.environ.get("E2E_APPIUM_PORT", "4743"))
        except ValueError as exc:
            raise E2EError("Appium and iOS pool ports must be integers") from exc
        ports = list(range(wda, wda + len(pool))) + list(range(mjpeg, mjpeg + len(pool))) + [appium_port]
        if len(set(ports)) != len(ports) or any(port < 1 or port > 65535 for port in ports):
            raise E2EError("Appium and iOS pool port ranges must be valid and non-overlapping")
        return cls(
            repo=repo,
            python=Path(os.environ["E2E_PYTHON"]).expanduser(),
            build_root=Path(os.environ["E2E_BUILD_ROOT"]).expanduser() if os.environ.get("E2E_BUILD_ROOT") else None,
            ios_udid=os.environ.get("E2E_IOS_SIMULATOR_UDID", ""),
            android_avd=os.environ.get("E2E_ANDROID_AVD", ""),
            android_serial=os.environ.get("E2E_ANDROID_SERIAL", "emulator-5584"),
            android_sdk=Path(os.environ.get("ANDROID_HOME", "~/Library/Android/sdk")).expanduser(),
            appium=os.environ.get("E2E_APPIUM_BIN") or shutil.which("appium") or "appium",
            appium_port=appium_port,
            ios_pool=pool,
            ios_wda_port_base=wda,
            ios_mjpeg_port_base=mjpeg,
            ios_wda_root=Path(os.environ["SDD_E2E_IOS_WDA_ROOT"]).expanduser()
                if os.environ.get("SDD_E2E_IOS_WDA_ROOT") else None,
        )
