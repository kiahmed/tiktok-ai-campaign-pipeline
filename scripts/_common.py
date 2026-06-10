"""Shared helpers for the standalone cron scripts.

The cron scripts are decoupled from the web server: they read the interval and
target from configuration (.env) and call the API's existing endpoints over
HTTP. Run a script with no args to loop forever (self-scheduling), or with
``--once`` to run a single time (e.g. when invoked by OS cron / Task Scheduler).
``--dry-run`` prints the calls it would make without sending them.
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Callable

import requests

from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger("cron")


def parse_args(description: str) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--once", action="store_true", help="Run a single time and exit.")
    p.add_argument("--dry-run", action="store_true", help="Print the request without sending it.")
    return p.parse_args()


def http_post(path: str, body: dict, *, dry_run: bool = False, timeout: int = 900):
    """POST to the configured API. Long timeout — video generation blocks."""
    url = get_settings().api_base_url.rstrip("/") + path
    if dry_run:
        logger.info("[dry-run] POST %s %s", url, body)
        return None
    resp = requests.post(url, json=body, timeout=timeout)
    if resp.status_code >= 400:
        logger.error("POST %s -> %s: %s", url, resp.status_code, resp.text[:300])
    else:
        logger.info("POST %s -> %s", url, resp.status_code)
    return resp


def run_loop(label: str, interval_seconds: float, action: Callable[[], None], *, once: bool) -> None:
    """Run ``action`` now, then every ``interval_seconds`` until stopped."""
    configure_logging(get_settings().log_level)
    log = logging.getLogger(f"cron.{label}")
    log.info("%s cron starting (interval=%.0fs, once=%s)", label, interval_seconds, once)
    while True:
        try:
            action()
        except Exception:  # a failed tick must not kill the loop
            log.exception("%s tick failed", label)
        if once:
            return
        time.sleep(max(1.0, interval_seconds))
