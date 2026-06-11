from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.entities import ProductInput, ScriptResult, VideoResult
from app.core.entities.profile import CreativeDirectives


class VideoGenerator(ABC):
    """Generates a vertical 9:16 ad video from a product image + script.

    Implementations: Pexo (default), Creatify, Arcads, Kling, ...

    Implementations may need to poll an async job; the contract is simply that
    ``generate`` returns only once a downloadable video URL is available.
    """

    name: str = "abstract"

    # True for providers that return a FINISHED video with its own voiceover and
    # lip-sync baked in (e.g. HeyGen avatars). The pipeline then skips the
    # separate ElevenLabs voiceover + ffmpeg merge / Kling lip-sync steps.
    produces_audio: bool = False

    @abstractmethod
    def generate(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> VideoResult:
        """Produce a vertical MP4 ad video and return a downloadable result.

        ``directives`` carry tested creative cues (narrator/presenter gender,
        background-music style). Providers apply whichever their API supports.

        Raises:
            VideoGenerationError: if generation fails or times out.
        """
        raise NotImplementedError
