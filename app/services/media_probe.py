"""Optional media inspection via ffprobe (part of ffmpeg).

Used by Quality Review to deep-verify a downloaded video's real resolution and
frame rate against the platform spec. ffmpeg is NOT a hard dependency: if
``ffprobe`` isn't on PATH, :func:`probe_media` returns None and the deep check
is skipped (the dependency-free file-size/format checks still run).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess

logger = logging.getLogger("media.probe")


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_media(path: str) -> dict | None:
    """Return {'width', 'height', 'fps'} for a video, or None if unavailable."""
    if not ffprobe_available():
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        stream = json.loads(proc.stdout)["streams"][0]
        rate = stream.get("avg_frame_rate", "0/1")
        num, _, den = rate.partition("/")
        fps = round(float(num) / float(den)) if den and float(den) else 0
        return {"width": int(stream["width"]), "height": int(stream["height"]), "fps": fps}
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        logger.warning("ffprobe failed for %s; skipping media deep-check", path, exc_info=True)
        return None
