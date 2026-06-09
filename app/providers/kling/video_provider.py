"""Kling implementation of the VideoGenerator interface (drop-in for Pexo)."""
from __future__ import annotations

from app.core.entities import ProductInput, ScriptResult
from app.core.entities.profile import CreativeDirectives
from app.providers.base_video import PollingVideoProvider


class KlingVideoProvider(PollingVideoProvider):
    name = "kling"
    create_path = "/v1/videos/image2video"
    status_path = "/v1/videos/image2video/{job_id}"
    status_done = {"completed", "succeeded", "success", "succeed"}

    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        prompt = script.text
        # Kling is prompt-driven, so fold creative cues into the prompt text.
        if directives:
            extra = " ".join(x for x in [directives.format, directives.music] if x)
            if extra:
                prompt = f"{prompt}\n[style: {extra}]"
        return {
            "image": product.image_url,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "mode": "std",
        }

    def parse_status(self, data: dict) -> tuple[str, str | None, float | None]:
        # Kling nests results under data.task_result.videos[0].url
        body = data.get("data", data)
        status = str(body.get("task_status", body.get("status", ""))).lower()
        url = None
        result = body.get("task_result") or {}
        videos = result.get("videos") or []
        if videos:
            url = videos[0].get("url")
        return status, url, None
