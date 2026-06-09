"""Loads brand / audience / creative-rules profiles.

Backed by a JSON file for now (fast, single-brand). The rest of the system
depends only on :class:`Profiles`, so this can be swapped for DB-backed
profiles later without touching the agents.
"""
from __future__ import annotations

import json
import logging
import os

from app.core.entities.profile import (
    AudienceProfile,
    AudienceSegment,
    BrandProfile,
    CreativeDirectives,
    CreativeRules,
    Profiles,
)

logger = logging.getLogger("service.profiles")


class ProfileService:
    def __init__(self, path: str = "config/profiles.json") -> None:
        self._path = path

    def load(self) -> Profiles:
        """Return profiles from disk, falling back to safe defaults if missing."""
        if not os.path.exists(self._path):
            logger.warning("Profiles file not found at %s; using defaults", self._path)
            return Profiles(BrandProfile(), AudienceProfile(), CreativeRules())
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read profiles (%s); using defaults", exc)
            return Profiles(BrandProfile(), AudienceProfile(), CreativeRules())

        creative = CreativeDirectives(**{**_CREATIVE_DEFAULTS, **data.get("creative", {})})

        brand = BrandProfile(**{**_BRAND_DEFAULTS, **data.get("brand", {})})
        segments = [
            AudienceSegment(
                name=s.get("name", "general"),
                pains=s.get("pains", []),
                desires=s.get("desires", []),
            )
            for s in data.get("audience", {}).get("segments", [])
        ]
        audience = AudienceProfile(segments=segments)
        rules = CreativeRules(**{**_RULES_DEFAULTS, **data.get("rules", {})})
        return Profiles(brand=brand, audience=audience, rules=rules, creative=creative)


# Only keys that exist on the dataclasses are passed through.
_BRAND_DEFAULTS = {
    "name": "", "voice": "", "tone_words": [], "value_props": [], "banned_words": [],
}
_RULES_DEFAULTS: dict = {}
_CREATIVE_DEFAULTS = {"narrator": "", "format": "", "music": "", "notes": ""}
