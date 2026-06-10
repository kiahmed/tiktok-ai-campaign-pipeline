"""ElevenLabs implementation of the VoiceGenerator interface.

Synthesizes the spoken ad script into an MP3 voiceover via the ElevenLabs
text-to-speech REST API, and saves it locally to be merged onto the video.
"""
from __future__ import annotations

import logging
import os

import requests

from app.core.entities.voice import VoiceResult
from app.core.exceptions import ConfigurationError, VoiceGenerationError
from app.core.http import translate_network_errors
from app.core.interfaces import VoiceGenerator
from app.core.retry import with_retry

logger = logging.getLogger("provider.elevenlabs")


class ElevenLabsVoiceProvider(VoiceGenerator):
    name = "elevenlabs"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        *,
        model_id: str = "eleven_multilingual_v2",
        base_url: str = "https://api.elevenlabs.io",
        storage_dir: str = "generated_videos",
        timeout: int = 120,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> None:
        if not api_key or not voice_id:
            raise ConfigurationError("ElevenLabs needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID")
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._base = base_url.rstrip("/")
        self._dir = storage_dir
        self._timeout = timeout
        self._stability = stability
        self._similarity = similarity_boost
        os.makedirs(self._dir, exist_ok=True)

    def synthesize(self, text: str, *, file_name: str) -> VoiceResult:
        if not text.strip():
            raise VoiceGenerationError("empty text for TTS", provider=self.name)
        logger.info("Synthesizing voiceover with ElevenLabs (voice=%s)", self._voice_id)
        audio = self._call_api(text)
        dest = os.path.join(self._dir, file_name)
        with open(dest, "wb") as fh:
            fh.write(audio)
        if os.path.getsize(dest) == 0:
            os.remove(dest)
            raise VoiceGenerationError("ElevenLabs returned empty audio", provider=self.name)
        logger.info("Voiceover saved (%d bytes): %s", os.path.getsize(dest), dest)
        return VoiceResult(local_path=dest, provider=self.name, format="mp3")

    @translate_network_errors(VoiceGenerationError)
    @with_retry()
    def _call_api(self, text: str) -> bytes:
        url = f"{self._base}/v1/text-to-speech/{self._voice_id}"
        resp = requests.post(
            url,
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": self._model_id,
                "voice_settings": {
                    "stability": self._stability,
                    "similarity_boost": self._similarity,
                },
            },
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise VoiceGenerationError(
                f"HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        return resp.content
