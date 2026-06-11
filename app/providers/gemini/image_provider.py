"""Imagen (Google Generative Language API) implementation of ImageGenerator.

Generates a still image from a text prompt via the Imagen ``:predict`` endpoint,
reusing the same Google API key as the Gemini script provider. Used here to
render a 9:16 background scene from the script so a HeyGen avatar can be placed
in front of it.

NOTE: Imagen access depends on your Google API key/tier. If your key returns 404
for the model, set IMAGEN_MODEL to one you have access to, or disable background
generation (HEYGEN_BACKGROUND_MODE=none).
"""
from __future__ import annotations

import base64
import logging
import time

import requests

from app.core.exceptions import ConfigurationError, ImageGenerationError
from app.core.http import translate_network_errors
from app.core.interfaces import ImageGenerator
from app.core.retry import with_retry

logger = logging.getLogger("provider.imagen")

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _aspect_ratio(width: int, height: int) -> str:
    """Map pixel dims to the closest Imagen aspect_ratio token."""
    if height > width:
        return "9:16"
    if width > height:
        return "16:9"
    return "1:1"


class GeminiImageProvider(ImageGenerator):
    name = "imagen"

    def __init__(
        self,
        api_key: str,
        model: str = "imagen-4.0-generate-001",
        timeout: int = 120,
        retries_429: int = 1,
        retry_wait: float = 20.0,
    ) -> None:
        if not api_key:
            raise ConfigurationError("Imagen needs a Google API key (GEMINI_API_KEY)")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._retries_429 = max(0, retries_429)
        self._retry_wait = max(0.0, retry_wait)

    @translate_network_errors(ImageGenerationError)
    @with_retry()
    def generate(self, prompt: str, *, width: int = 1080, height: int = 1920) -> bytes:
        url = f"{_BASE}/{self._model}:predict"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": _aspect_ratio(width, height)},
        }
        logger.info("Generating image with %s (%s)", self._model, _aspect_ratio(width, height))
        last_text = ""
        for attempt in range(self._retries_429 + 1):
            resp = requests.post(
                url, params={"key": self._api_key}, json=payload, timeout=self._timeout
            )
            # 429 = quota / rate limit. Often per-minute, so wait and retry once.
            if resp.status_code == 429:
                last_text = (resp.text or "")[:200]
                if attempt < self._retries_429:
                    wait = self._retry_wait
                    ra = resp.headers.get("Retry-After")
                    if ra and str(ra).isdigit():
                        wait = float(ra)
                    logger.warning(
                        "Imagen rate-limited (429); waiting %.0fs then retrying (%d/%d)",
                        wait, attempt + 1, self._retries_429,
                    )
                    time.sleep(wait)
                    continue
                raise ImageGenerationError(
                    f"HTTP 429 quota exhausted (after {self._retries_429} retries). "
                    f"Raise your Imagen quota or reduce image calls. {last_text}",
                    provider=self.name,
                )
            if resp.status_code >= 400:
                raise ImageGenerationError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
                )
            data = resp.json()
            try:
                b64 = data["predictions"][0]["bytesBase64Encoded"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ImageGenerationError(
                    f"Unexpected Imagen response shape: {str(data)[:300]}", provider=self.name
                ) from exc
            return base64.b64decode(b64)
        raise ImageGenerationError("Imagen: exhausted retries", provider=self.name)
