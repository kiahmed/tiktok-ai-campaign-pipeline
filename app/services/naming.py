"""Helpers for product slugs and timestamped video filenames."""
from __future__ import annotations

import re
from datetime import datetime


def slugify(value: str) -> str:
    """Convert a product name into a filesystem-safe slug.

    "Rosemary Hair Growth Oil" -> "rosemary_hair_growth_oil"
    """
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "product"


def video_filename(slug: str, *, now: datetime | None = None) -> str:
    """Build ``<slug>_<YYYYMMDD>_<HHMMSS>.mp4``."""
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{slug}_{stamp}.mp4"
