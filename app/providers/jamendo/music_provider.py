"""Jamendo music provider — search by keyword and pick a track at random.

Jamendo has a real (free) music API: GET /v3.0/tracks searches by keyword/tags
and returns a downloadable MP3 per track. We fetch a batch for the configured
query (e.g. "advertisement background"), keep the downloadable ones, pick one at
random, and download it for the ffmpeg music mix.

Free client_id from https://devportal.jamendo.com/. The methods degrade
gracefully (return None/False on any failure) so music never breaks a video.

LICENSING NOTE: Jamendo tracks are Creative Commons — many free downloads are
CC-BY (attribution) or CC-NC (no commercial use). For PAID ads, verify each
track's license_ccurl (logged per video) or use Jamendo's commercial program.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import requests

from app.core.exceptions import ConfigurationError

logger = logging.getLogger("provider.jamendo")


@dataclass(slots=True)
class MusicTrack:
    id: str
    name: str
    artist: str
    download_url: str
    license: str | None = None
    duration: float | None = None


class JamendoMusicProvider:
    name = "jamendo"

    def __init__(
        self,
        client_id: str,
        *,
        base_url: str = "https://api.jamendo.com/v3.0",
        query: str = "advertisement background",
        limit: int = 50,
        commercial_only: bool = True,
        timeout: int = 60,
        rng: random.Random | None = None,
    ) -> None:
        if not client_id:
            raise ConfigurationError("Jamendo needs JAMENDO_CLIENT_ID")
        self._cid = client_id
        self._base = base_url.rstrip("/")
        self._query = query
        self._limit = max(1, limit)
        self._commercial_only = commercial_only
        self._timeout = timeout
        self._rng = rng or random.Random()

    @staticmethod
    def _commercial_ok(license_url: str | None) -> bool:
        """True if the CC license allows commercial use AND derivatives (mixing)."""
        u = (license_url or "").lower()
        if not u:
            return False                       # unknown => exclude to be safe
        if "-nc" in u or "-nd" in u:
            return False                       # NonCommercial or NoDerivatives
        return "creativecommons.org" in u or "publicdomain" in u  # by / by-sa / cc0

    def pick(self) -> MusicTrack | None:
        """Search the query and return a random downloadable track (or None)."""
        params = {
            "client_id": self._cid,
            "format": "json",
            "limit": self._limit,
            "search": self._query,
            "audioformat": "mp32",
            "audiodlformat": "mp32",
        }
        try:
            resp = requests.get(f"{self._base}/tracks/", params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("Jamendo search failed: %s", exc)
            return None
        if resp.status_code >= 400:
            logger.warning("Jamendo HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        try:
            results = resp.json().get("results", []) or []
        except ValueError:
            return None

        usable = [t for t in results if t.get("audiodownload") and t.get("audiodownload_allowed")]
        if not usable:  # fall back to any with a download URL
            usable = [t for t in results if t.get("audiodownload")]
        if self._commercial_only:
            allowed = [t for t in usable if self._commercial_ok(t.get("license_ccurl"))]
            if not allowed:
                logger.warning(
                    "Jamendo: no commercially-usable tracks for %r (all NC/ND). "
                    "Skipping music — try a different MUSIC_QUERY or set MUSIC_COMMERCIAL_ONLY=false.",
                    self._query,
                )
                return None
            usable = allowed
        if not usable:
            logger.warning("Jamendo returned no downloadable tracks for %r", self._query)
            return None

        t = self._rng.choice(usable)
        try:
            duration = float(t.get("duration")) if t.get("duration") else None
        except (TypeError, ValueError):
            duration = None
        return MusicTrack(
            id=str(t.get("id", "")),
            name=t.get("name", ""),
            artist=t.get("artist_name", ""),
            download_url=t.get("audiodownload", ""),
            license=t.get("license_ccurl"),
            duration=duration,
        )

    def download(self, url: str, dest_path: str) -> bool:
        try:
            resp = requests.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("Jamendo track download failed: %s", exc)
            return False
        if resp.status_code >= 400 or not resp.content:
            logger.warning("Jamendo track download HTTP %s", resp.status_code)
            return False
        try:
            with open(dest_path, "wb") as fh:
                fh.write(resp.content)
        except OSError:
            return False
        return True
