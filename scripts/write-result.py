#!/usr/bin/env python3

from pathlib import Path
import sys

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.tools.write_result import main


if __name__ == "__main__":
    raise SystemExit(main())
