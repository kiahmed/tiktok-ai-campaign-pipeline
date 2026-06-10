from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.entities.voice import VoiceResult


class VoiceGenerator(ABC):
    """Synthesizes a voiceover (TTS) from the spoken ad script.

    Implementations: ElevenLabs (default), ...
    """

    name: str = "abstract"

    @abstractmethod
    def synthesize(self, text: str, *, file_name: str) -> VoiceResult:
        """Produce a voiceover audio file from ``text`` and return its path.

        Raises:
            VoiceGenerationError: if synthesis fails.
        """
        raise NotImplementedError
