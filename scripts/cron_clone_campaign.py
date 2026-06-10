"""Cron: deep-clone the template campaign (+ ad groups) on an interval.

Calls ``POST /campaigns/clone``. The newly cloned campaign becomes the "latest",
so subsequent generated ads publish into its ad groups.

Config (.env):
  CAMPAIGN_CLONE_INTERVAL_DAYS   how often (default 30 = monthly)
  CAMPAIGN_NAME_PREFIX           name prefix (date is appended)
  API_BASE_URL                   the running API

Usage:
  python -m scripts.cron_clone_campaign           # loop monthly
  python -m scripts.cron_clone_campaign --once     # one clone (for OS cron)
  python -m scripts.cron_clone_campaign --once --dry-run
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.config import get_settings
from scripts._common import http_post, parse_args, run_loop

log = logging.getLogger("cron.clone")


def clone(dry_run: bool = False) -> None:
    settings = get_settings()
    name = f"{settings.campaign_name_prefix} {datetime.now():%Y-%m-%d}"
    log.info("Cloning campaign -> '%s'", name)
    http_post("/campaigns/clone", {"name": name, "clone_adgroups": True}, dry_run=dry_run)


def main() -> None:
    args = parse_args("Deep-clone the template campaign on an interval.")
    interval = get_settings().campaign_clone_interval_days * 86400.0
    run_loop("clone", interval, lambda: clone(args.dry_run), once=args.once)


if __name__ == "__main__":
    main()
