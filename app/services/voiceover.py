"""Adds an ElevenLabs voiceover onto a (silent) video and merges via ffmpeg.

Shared by the agent pipeline and the one-shot CreativeService so both produce
voiced clips. Best-effort: if voice is disabled, the TTS fails, or ffmpeg is
missing, it returns the original silent video so the pipeline still completes.
"""
from __future__ import annotations

import logging
import os

from app.core.exceptions import VoiceGenerationError
from app.services.video_merge import VideoMerger

logger = logging.getLogger("service.voiceover")


class VoiceoverService:
    def __init__(self, *, voice_generator=None, merger: VideoMerger | None = None, enabled: bool = False) -> None:
        self._voice = voice_generator
        self._merger = merger
        self._enabled = enabled

    def apply(self, *, slug: str, video_path: str, file_name: str, text: str) -> tuple[str, str]:
        """Return (final_video_path, final_file_name); silent video on any skip."""
        if not (self._enabled and self._voice and self._merger and text.strip()):
            return video_path, file_name
        try:
            voice = self._voice.synthesize(text, file_name=f"{slug}_vo.mp3")
        except VoiceGenerationError:
            logger.warning("Voiceover failed; keeping silent video", exc_info=True)
            return video_path, file_name

        merged_name = file_name.replace(".mp4", "_voiced.mp4")
        merged_path = os.path.join(os.path.dirname(video_path) or ".", merged_name)
        out = self._merger.merge(video_path, voice.local_path, merged_path)
        if out:
            return out, merged_name
        logger.warning("Merge unavailable; keeping silent video")
        return video_path, file_name
