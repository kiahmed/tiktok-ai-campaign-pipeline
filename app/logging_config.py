"""Application-wide logging setup.

Logs go to both stdout (for Docker / container log collection) and a rotating
file under ``logs/``. Call :func:`configure_logging` once at startup.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_DIR = "logs"
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger. Idempotent — safe to call more than once."""
    global _configured
    if _configured:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level.upper())

    formatter = logging.Formatter(_LOG_FORMAT)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Tame noisy third-party loggers.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor for a named logger."""
    return logging.getLogger(name)
