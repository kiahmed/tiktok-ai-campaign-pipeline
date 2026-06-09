"""Google Veo 3.1 (via the Gemini API) implementation of VideoGenerator.

Veo generation is a long-running operation, not the generic "submit -> status
URL" shape, so this is its own provider:

  1. POST  /models/{model}:predictLongRunning  → an operation name
  2. GET   /{operation}                         → poll until ``done``
  3. the result's video URI is downloaded with the API key appended

It does **image-to-video** when the product image is reachable (uses it as the
opening frame), otherwise falls back to text-to-video. Veo 3 also generates
audio, so the spoken script is folded into the prompt.

NOTE: Veo's request/response field names have evolved across preview versions.
The endpoint and the response-parsing are written defensively and isolated in
small methods/constants — if your Veo 3.1 build differs, adjust here only; the
``VideoGenerator`` contract and everything downstream stay identical.
"""
from __future__ import annotations

import base64
import logging
import time

import requests

from app.core.entities import ProductInput, ScriptResult, VideoResult
from app.core.entities.profile import CreativeDirectives
from app.core.exceptions import ConfigurationError, VideoGenerationError
from app.core.http import translate_network_errors
from app.core.interfaces import VideoGenerator
from app.core.retry import with_retry

logger = logging.getLogger("provider.veo")


class VeoVideoProvider(VideoGenerator):
    name = "veo"

    def __init__(
        self,
        api_key: str,
        model: str = "veo-3.1-generate-preview",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        *,
        aspect_ratio: str = "9:16",
        resolution: str = "1080p",
        timeout: int = 60,
        poll_interval: float = 10.0,
        max_poll_seconds: float = 600.0,
    ) -> None:
        if not api_key:
            raise ConfigurationError("VEO_API_KEY (or GEMINI_API_KEY) is not set")
        self._api_key = api_key
        self._model = model
        self._base = base_url.rstrip("/")
        self._aspect_ratio = aspect_ratio
        self._resolution = resolution
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._max_poll_seconds = max_poll_seconds

    # ---- VideoGenerator contract ----
    def generate(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> VideoResult:
        prompt = self._build_prompt(product, script, directives)
        image = self._fetch_image(product.image_url)
        logger.info("Submitting Veo job (model=%s, image=%s)", self._model, bool(image))
        operation = self._submit(prompt, image)
        logger.info("Veo operation started: %s; polling", operation)
        uri = self._poll(operation)
        return VideoResult(
            download_url=self._with_key(uri),
            provider=self.name,
            external_job_id=operation,
            format="mp4",
            aspect_ratio=self._aspect_ratio,
        )

    # ---- prompt + image ----
    @staticmethod
    def _build_prompt(
        product: ProductInput, script: ScriptResult, directives: CreativeDirectives | None
    ) -> str:
        speaker = "a person"
        parts: list[str] = []
        if directives and directives.narrator:
            speaker = f"a {directives.narrator} narrator"
        parts.append(
            f"Vertical 9:16 UGC-style TikTok ad. {speaker} speaks directly to the "
            "camera, handheld, authentic."
        )
        if directives and directives.format:
            parts.append(f"Story: {directives.format}.")
        parts.append(f'They say: "{script.text}"')
        if directives and directives.music:
            parts.append(f"Background music: {directives.music}.")
        parts.append(f"Product featured: {product.name}.")
        return " ".join(parts)

    def _fetch_image(self, image_url: str) -> tuple[str, str] | None:
        """Download the product image -> (base64, mime). None on any failure."""
        try:
            resp = requests.get(image_url, timeout=self._timeout)
            if resp.status_code >= 400 or not resp.content:
                logger.warning("Veo: product image unreachable (%s); text-to-video", resp.status_code)
                return None
            mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            return base64.b64encode(resp.content).decode("ascii"), mime
        except requests.RequestException as exc:
            logger.warning("Veo: image fetch failed (%s); text-to-video", exc)
            return None

    # ---- Veo REST ----
    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _submit(self, prompt: str, image: tuple[str, str] | None) -> str:
        instance: dict = {"prompt": prompt}
        if image:
            b64, mime = image
            instance["image"] = {"bytesBase64Encoded": b64, "mimeType": mime}
        # NOTE: veo-3.1 on the Gemini API accepts aspectRatio + resolution.
        # It does NOT accept numberOfVideos/sampleCount (returns 400) — it
        # always generates one clip.
        payload = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": self._aspect_ratio,   # "9:16"
                "resolution": self._resolution,      # "1080p" => 1080x1920 for 9:16
            },
        }
        resp = requests.post(
            f"{self._base}/models/{self._model}:predictLongRunning",
            params={"key": self._api_key},
            json=payload,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(
                f"submit HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        name = resp.json().get("name")
        if not name:
            raise VideoGenerationError("no operation name in Veo response", provider=self.name)
        return name

    def _poll(self, operation: str) -> str:
        waited = 0.0
        while waited <= self._max_poll_seconds:
            op = self._poll_once(operation)
            if op.get("done"):
                if op.get("error"):
                    raise VideoGenerationError(
                        f"Veo operation failed: {op['error']}", provider=self.name
                    )
                uri = _extract_video_uri(op.get("response", {}))
                if not uri:
                    raise VideoGenerationError(
                        f"Veo finished but no video URI: {op.get('response')}", provider=self.name
                    )
                return uri
            time.sleep(self._poll_interval)
            waited += self._poll_interval
        raise VideoGenerationError(
            f"Veo operation timed out after {self._max_poll_seconds:.0f}s", provider=self.name
        )

    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _poll_once(self, operation: str) -> dict:
        resp = requests.get(
            f"{self._base}/{operation}", params={"key": self._api_key}, timeout=self._timeout
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(
                f"poll HTTP {resp.status_code}: {resp.text[:200]}", provider=self.name
            )
        return resp.json()

    def _with_key(self, uri: str) -> str:
        """Append the API key so VideoStorageService can download the file."""
        if "key=" in uri:
            return uri
        sep = "&" if "?" in uri else "?"
        return f"{uri}{sep}key={self._api_key}"


def _extract_video_uri(response: dict) -> str | None:
    """Find the generated video URI across known Veo response shapes."""
    if not isinstance(response, dict):
        return None
    # Common shapes seen across Veo preview/GA on the Gemini API.
    candidates = [
        ("generateVideoResponse", "generatedSamples"),
        ("generateVideoResponse", "generatedVideos"),
        ("generatedSamples",),
        ("generatedVideos",),
        ("videos",),
    ]
    for path in candidates:
        node = response
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, list) and node:
            video = node[0].get("video") if isinstance(node[0], dict) else None
            uri = (video or {}).get("uri") if isinstance(video, dict) else None
            uri = uri or (node[0].get("uri") if isinstance(node[0], dict) else None)
            if uri:
                return uri
    # Last resort: deep-search for any "uri" value.
    return _deep_find_uri(response)


def _deep_find_uri(obj) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "uri" and isinstance(v, str):
                return v
            found = _deep_find_uri(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _deep_find_uri(item)
            if found:
                return found
    return None
