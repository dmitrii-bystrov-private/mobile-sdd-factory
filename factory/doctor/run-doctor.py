#!/usr/bin/env python3
"""CLI entrypoint for the Constellation: Agent Runtime environment doctor."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factory.doctor.environment_doctor import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
