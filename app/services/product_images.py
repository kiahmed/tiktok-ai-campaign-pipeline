"""A pool of product image URLs to choose from at random.

Lets you keep several product photos (angles/shots) in a JSON config and have
the pipeline pick one per video for the product shot — so the product visual
varies between videos. The file may be either a JSON array of URLs or an object
with a "product_image_urls" (or "urls") array.
"""
from __future__ import annotations

import json
import logging
import os
import random

logger = logging.getLogger("service.product_images")


class ProductImagePool:
    def __init__(self, path: str = "config/product_images.json", rng: random.Random | None = None) -> None:
        self._path = path
        self._rng = rng or random.Random()
        self._urls: list[str] | None = None

    @property
    def urls(self) -> list[str]:
        if self._urls is None:
            self._urls = self._load()
        return self._urls

    def random_url(self, fallback: str = "") -> str:
        """Return a random URL from the pool, or ``fallback`` if the pool is empty."""
        urls = self.urls
        if not urls:
            return fallback
        return self._rng.choice(urls)

    # ---- internals ----
    def _load(self) -> list[str]:
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read product images (%s): %s", self._path, exc)
            return []
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = data.get("product_image_urls") or data.get("urls") or []
        else:
            raw = []
        return [u.strip() for u in raw if isinstance(u, str) and u.strip()]
