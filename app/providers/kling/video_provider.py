"""Kling AI implementation of the VideoGenerator interface (default).

Kling generates clips of 3–15s (kling-v3 supports up to 15s). It follows the
submit-then-poll pattern of :class:`PollingVideoProvider`; only the auth and
payload differ.

IMPORTANT: image2video has NO aspect_ratio field — the output aspect ratio
follows the INPUT image. Provide a 9:16 image for a vertical TikTok video, or
use Kling's text2video endpoint (which does take aspect_ratio).

Auth: the official Kling API uses a **JWT** signed with an access key + secret
key (HS256, short-lived). If instead you call Kling through a gateway
(PiAPI / fal / Replicate ...) with a plain bearer key, set ``KLING_API_KEY`` and
leave the access/secret blank.

NOTE: Kling's base URL, model names and field names vary by region/plan. They
are config-driven / isolated here — adjust if your account differs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import requests

from app.core.entities import ProductInput, ScriptResult, VideoResult
from app.core.entities.profile import CreativeDirectives
from app.core.exceptions import ConfigurationError, VideoGenerationError
from app.core.http import translate_network_errors
from app.core.retry import with_retry
from app.providers.base_video import PollingVideoProvider


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(access_key: str, secret_key: str, *, ttl: int = 1800) -> str:
    """Build a short-lived HS256 JWT for the Kling API (no external dependency)."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": access_key, "exp": now + ttl, "nbf": now - 5}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = hmac.new(secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


class KlingVideoProvider(PollingVideoProvider):
    name = "kling"
    create_path = "/v1/videos/image2video"
    status_path = "/v1/videos/image2video/{job_id}"
    status_done = {"succeed", "succeeded", "success", "completed"}
    status_failed = {"failed", "error"}

    def __init__(
        self,
        *,
        access_key: str = "",
        secret_key: str = "",
        api_key: str = "",
        base_url: str = "https://api-singapore.klingai.com",
        model: str = "kling-v1",
        duration: str = "10",
        mode: str = "std",
        prepare_image: bool = True,
        image_width: int = 1080,
        image_height: int = 1920,
        timeout: int = 60,
        poll_interval: float = 10.0,
        max_poll_seconds: float = 600.0,
    ) -> None:
        if not ((access_key and secret_key) or api_key):
            raise ConfigurationError(
                "Kling needs KLING_ACCESS_KEY + KLING_SECRET_KEY (JWT), "
                "or KLING_API_KEY (gateway)"
            )
        self._access_key = access_key
        self._secret_key = secret_key
        self._model = model
        self._duration = str(duration)
        self._mode = mode
        self._prepare_image = prepare_image
        self._image_width = image_width
        self._image_height = image_height
        # base_video validates a non-empty api_key; pass the access key when in
        # JWT mode (it is not used as a bearer there — auth_headers overrides).
        super().__init__(
            api_key=api_key or access_key,
            base_url=base_url,
            timeout=timeout,
            poll_interval=poll_interval,
            max_poll_seconds=max_poll_seconds,
        )

    # ---- auth: JWT (access+secret) or bearer (gateway) ----
    def auth_headers(self) -> dict[str, str]:
        if self._access_key and self._secret_key:
            token = make_jwt(self._access_key, self._secret_key)
        else:
            token = self._api_key
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ---- payload / parsing ----
    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        # Use the visual prompt (what the video shows); the spoken script is the
        # voiceover and is a poor video prompt. Fall back to the script text.
        prompt = script.visual_prompt or script.text
        if directives:
            extra = " ".join(x for x in [directives.format, directives.music] if x)
            if extra:
                prompt = f"{prompt}\n[style: {extra}]"

        # image2video output ratio follows the INPUT image. Pad/fit the product
        # image to 9:16 and send raw base64; fall back to the URL if prep fails.
        image_field = product.image_url
        if self._prepare_image:
            from app.services.image_prep import url_to_vertical_b64

            b64 = url_to_vertical_b64(
                product.image_url, width=self._image_width, height=self._image_height
            )
            if b64:
                image_field = b64
                self._log.info("Prepared product image to %dx%d", self._image_width, self._image_height)

        payload = {
            "model_name": self._model,
            "image": image_field,         # 9:16 base64 (or URL fallback)
            "prompt": prompt,
            "duration": self._duration,   # "3".."15" (v3 supports up to 15)
            "mode": self._mode,           # std=720p, pro=1080p, 4k=4K
        }
        # cfg_scale is only supported on v1.x models (v2.x/v3 reject/ignore it).
        if self._model.startswith("kling-v1"):
            payload["cfg_scale"] = 0.5
        return payload

    def parse_job_id(self, data: dict) -> str | None:
        body = data.get("data", data)
        return body.get("task_id") or body.get("id")

    def parse_status(self, data: dict) -> tuple[str, str | None, float | None]:
        body = data.get("data", data)
        status = str(body.get("task_status", body.get("status", ""))).lower()
        url = None
        duration = None
        videos = (body.get("task_result") or {}).get("videos") or []
        if videos:
            url = videos[0].get("url")
            try:
                duration = float(videos[0].get("duration"))
            except (TypeError, ValueError):
                duration = None
        return status, url, duration

    # ------------------------------------------------------------------ #
    # Talking-head mode: text2video (person) + lip-sync to a voiceover.
    # NOTE: endpoint paths / field names per Kling's API — verify vs your plan.
    # ------------------------------------------------------------------ #
    def text2video(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> VideoResult:
        """Generate a person/scene video from the prompt (text2video has a real
        aspect_ratio field, so output is 9:16 without an input image)."""
        prompt = script.visual_prompt or script.text
        if directives:
            extra = " ".join(x for x in [directives.format] if x)
            if extra:
                prompt = f"{prompt}\n[style: {extra}]"
        payload = {
            "model_name": self._model,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "duration": self._duration,
            "mode": self._mode,
        }
        self._log.info("Submitting Kling text2video for product=%s", product.name)
        task_id = self._kling_submit("/v1/videos/text2video", payload)
        url, video_id, duration = self._kling_poll("/v1/videos/text2video/{job_id}", task_id)
        return VideoResult(
            download_url=url, provider=self.name, external_job_id=video_id or task_id,
            aspect_ratio="9:16", duration_seconds=duration,
        )

    def lip_sync(self, *, audio_path: str, video_id: str | None = None, video_url: str | None = None) -> VideoResult:
        """Lip-sync an existing Kling video to a local audio file (the VO)."""
        with open(audio_path, "rb") as fh:
            audio_b64 = base64.b64encode(fh.read()).decode("ascii")
        inp: dict = {"mode": "audio2video", "audio_type": "file", "audio_file": audio_b64}
        if video_id:
            inp["video_id"] = video_id
        elif video_url:
            inp["video_url"] = video_url
        else:
            raise VideoGenerationError("lip_sync needs a video_id or video_url", provider=self.name)
        self._log.info("Submitting Kling lip-sync (video_id=%s)", video_id)
        task_id = self._kling_submit("/v1/videos/lip-sync", {"input": inp})
        url, _vid, duration = self._kling_poll("/v1/videos/lip-sync/{job_id}", task_id)
        return VideoResult(
            download_url=url, provider=self.name, external_job_id=task_id,
            aspect_ratio="9:16", duration_seconds=duration,
        )

    # ---- generic submit / poll for the extra Kling endpoints ----
    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _kling_submit(self, path: str, payload: dict) -> str:
        resp = requests.post(
            f"{self._base_url}{path}", headers=self.auth_headers(), json=payload, timeout=self._timeout
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(f"{path} HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name)
        data = resp.json().get("data", {})
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise VideoGenerationError(f"no task_id from {path}", provider=self.name)
        return str(task_id)

    def _kling_poll(self, status_path: str, task_id: str) -> tuple[str, str | None, float | None]:
        waited = 0.0
        while waited <= self._max_poll_seconds:
            status, url, video_id, duration = self._kling_status(status_path, task_id)
            if status in self.status_done:
                if not url:
                    raise VideoGenerationError(f"task {task_id} done but no URL", provider=self.name)
                return url, video_id, duration
            if status in self.status_failed:
                raise VideoGenerationError(f"task {task_id} failed ({status})", provider=self.name)
            time.sleep(self._poll_interval)
            waited += self._poll_interval
        raise VideoGenerationError(f"task {task_id} timed out", provider=self.name)

    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _kling_status(self, status_path: str, task_id: str) -> tuple[str, str | None, str | None, float | None]:
        resp = requests.get(
            f"{self._base_url}{status_path.format(job_id=task_id)}",
            headers=self.auth_headers(), timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(f"status HTTP {resp.status_code}: {resp.text[:200]}", provider=self.name)
        body = resp.json().get("data", {})
        status = str(body.get("task_status", "")).lower()
        videos = (body.get("task_result") or {}).get("videos") or []
        url = videos[0].get("url") if videos else None
        video_id = videos[0].get("id") if videos else None
        duration = None
        if videos and videos[0].get("duration") is not None:
            try:
                duration = float(videos[0]["duration"])
            except (TypeError, ValueError):
                duration = None
        return status, url, video_id, duration
