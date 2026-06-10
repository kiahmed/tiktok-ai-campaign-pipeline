"""Merge a voiceover audio track onto a (silent) video using ffmpeg.

Kling's image2video output has no narration, so we mux the ElevenLabs voiceover
onto it here. ffmpeg is a system binary (not a pip package); if it is not on
PATH, :meth:`merge` returns None and the caller keeps the silent video.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger("service.video_merge")


class VideoMerger:
    def __init__(self, ffmpeg: str = "ffmpeg", timeout: int = 300) -> None:
        self._ffmpeg = ffmpeg
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    def merge(self, video_path: str, audio_path: str, out_path: str) -> str | None:
        """Mux ``audio_path`` onto ``video_path`` -> ``out_path``. None on skip/fail.

        Output duration = the VIDEO's duration: the voiceover is padded with
        trailing silence (``apad``) so the full video plays even if the VO is a
        bit shorter, and ``-shortest`` trims at the video's end. Video stream is
        copied; audio is encoded to AAC.
        """
        if not self.available:
            logger.warning("ffmpeg not found (%s); skipping merge (video stays silent)", self._ffmpeg)
            return None
        if not (os.path.exists(video_path) and os.path.exists(audio_path)):
            logger.warning("merge inputs missing: video=%s audio=%s", video_path, audio_path)
            return None

        cmd = [
            self._ffmpeg, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", "[1:a]apad[a]",   # pad the voiceover with silence
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            out_path,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ffmpeg merge failed to run: %s", exc)
            return None
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.warning("ffmpeg merge failed (rc=%s): %s", proc.returncode, proc.stderr[-300:])
            return None
        logger.info("Merged voiceover onto video -> %s", out_path)
        return out_path
