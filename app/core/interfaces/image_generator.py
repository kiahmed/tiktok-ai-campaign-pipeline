from __future__ import annotations

from abc import ABC, abstractmethod


class ImageGenerator(ABC):
    """Generates a still image from a text prompt (e.g. a video background)."""

    name: str = "abstract"

    @abstractmethod
    def generate(self, prompt: str, *, width: int = 1080, height: int = 1920) -> bytes:
        """Return the raw bytes of a generated image (JPEG/PNG).

        Raises:
            ImageGenerationError: if generation fails.
        """
        raise NotImplementedError
