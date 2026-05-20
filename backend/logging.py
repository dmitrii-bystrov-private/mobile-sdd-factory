"""Logging bootstrap for the Constellation: Agent Runtime backend."""

from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    """Configure process-wide logging once at startup."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
