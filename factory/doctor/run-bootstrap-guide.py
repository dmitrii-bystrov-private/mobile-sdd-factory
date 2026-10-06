#!/usr/bin/env python3
"""CLI entrypoint for bootstrap guidance."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factory.doctor.bootstrap_guidance import (
    build_bootstrap_guidance,
    format_bootstrap_guidance,
    json_dumps,
)
from factory.doctor.environment_doctor import build_report


def main(argv: list[str]) -> int:
    json_mode = "--json" in argv
    report = build_report(repo_root=REPO_ROOT)
    guidance = build_bootstrap_guidance(report)
    if json_mode:
        sys.stdout.write(json_dumps(guidance))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_bootstrap_guidance(guidance))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
