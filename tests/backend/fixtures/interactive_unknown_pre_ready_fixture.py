from __future__ import annotations

import sys
import time


def main() -> None:
    sys.stdout.write("SDD_FACTORY_ROLE_LAUNCHER_READY\n")
    sys.stdout.write("SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude lifecycle=persistent\n")
    sys.stdout.flush()
    for _ in range(4):
        sys.stdout.write("\x1b[?2026h\x1b[2D\x1b[4B\n\x1b[42C\x1b[2A6\n\n\n\x1b[2C\x1b[4A\x1b[?2026l")
        sys.stdout.flush()
        time.sleep(0.05)
    time.sleep(0.5)


if __name__ == "__main__":
    main()
