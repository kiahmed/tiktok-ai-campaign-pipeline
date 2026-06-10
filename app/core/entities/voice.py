from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VoiceResult:
    """A generated voiceover audio file, returned by any VoiceGenerator."""

    local_path: str
    provider: str
    format: str = "mp3"
    duration_seconds: float | None = None
