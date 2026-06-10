"""Talking-head video pipeline (creative_mode = talking_head).

Produces a lip-synced spokesperson clip:
    Kling text2video (person)  ->  ElevenLabs voiceover  ->  Kling lip-sync
The lip-sync output already contains the synced audio, so no ffmpeg merge.

Requires a Kling video provider (text2video + lip_sync). If no voice is
configured, it returns the silent person video (no lip-sync).
"""
from __future__ import annotations

import logging

from app.core.entities import ProductInput, ScriptResult
from app.core.entities.profile import CreativeDirectives
from app.core.exceptions import ConfigurationError, VoiceGenerationError
from app.services.naming import video_filename
from app.services.video_storage import VideoStorageService

logger = logging.getLogger("service.talking_head")


class TalkingHeadProducer:
    def __init__(self, *, video_generator, storage: VideoStorageService, voice_generator=None) -> None:
        self._kling = video_generator
        self._storage = storage
        self._voice = voice_generator

    def produce(
        self,
        *,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None,
        slug: str,
    ) -> tuple[str, str, str, float | None]:
        """Return (local_path, file_name, aspect_ratio, duration_seconds)."""
        if not (hasattr(self._kling, "text2video") and hasattr(self._kling, "lip_sync")):
            raise ConfigurationError("creative_mode=talking_head requires VIDEO_PROVIDER=kling")

        # Dynamic person generated from the prompt (face varies per ad).
        person = self._kling.text2video(product, script, directives)
        file_name = video_filename(slug)

        # No voice configured -> silent person video (cannot lip-sync).
        if not self._voice:
            logger.warning("No voice provider; talking-head video will be silent (no lip-sync)")
            path = self._storage.download(person.download_url, file_name)
            return path, file_name, person.aspect_ratio, person.duration_seconds

        try:
            voice = self._voice.synthesize(script.text, file_name=f"{slug}_vo.mp3")
        except VoiceGenerationError:
            logger.warning("Voiceover failed; using silent person video", exc_info=True)
            path = self._storage.download(person.download_url, file_name)
            return path, file_name, person.aspect_ratio, person.duration_seconds

        # Lip-sync the person video to the VO audio (audio2video) so the mouth
        # matches the EXACT spoken words.
        synced = self._kling.lip_sync(audio_path=voice.local_path, video_url=person.download_url)
        path = self._storage.download(synced.download_url, file_name)
        logger.info("Talking-head (lip-synced) video ready: %s", path)
        return path, file_name, synced.aspect_ratio, synced.duration_seconds
