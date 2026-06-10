"""Cron: generate a video + ad for each configured product, on an interval.

Calls ``POST /jobs`` (Strategist -> Veo -> QC -> Ad). The ad is routed into the
relevant ad group of the latest campaign automatically.

Config (.env):
  GENERATE_INTERVAL_HOURS   how often (default 24 = daily)
  GENERATE_PRODUCT_IDS      comma-separated product ids, e.g. "1,2,3"
  API_BASE_URL              the running API (default http://localhost:8000)

Usage:
  python -m scripts.cron_generate            # loop daily
  python -m scripts.cron_generate --once     # one pass (for OS cron)
  python -m scripts.cron_generate --once --dry-run
"""
from __future__ import annotations

import logging

from app.config import get_settings
from scripts._common import http_post, parse_args, run_loop

log = logging.getLogger("cron.generate")


def generate(dry_run: bool = False) -> None:
    settings = get_settings()
    ids = [x.strip() for x in settings.generate_product_ids.split(",") if x.strip()]
    if not ids:
        log.warning("GENERATE_PRODUCT_IDS is empty — nothing to generate.")
        return
    log.info("Generating a video/ad for %d product(s): %s", len(ids), ids)
    for pid in ids:
        http_post("/jobs", {"product_id": int(pid)}, dry_run=dry_run)


def main() -> None:
    args = parse_args("Generate videos/ads for configured products on an interval.")
    interval = get_settings().generate_interval_hours * 3600.0
    run_loop("generate", interval, lambda: generate(args.dry_run), once=args.once)


if __name__ == "__main__":
    main()
