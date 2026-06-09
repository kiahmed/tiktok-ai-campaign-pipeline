"""Creatify implementation of the VideoGenerator interface (drop-in for Pexo)."""
from __future__ import annotations

from app.core.entities import ProductInput, ScriptResult
from app.core.entities.profile import CreativeDirectives
from app.providers.base_video import PollingVideoProvider


class CreatifyVideoProvider(PollingVideoProvider):
    name = "creatify"
    create_path = "/api/link_to_videos/"
    status_path = "/api/link_to_videos/{job_id}/"

    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        payload = {
            "name": product.name,
            "script": script.text,
            "visual_url": product.image_url,
            "aspect_ratio": "9x16",
        }
        if directives and directives.narrator:
            payload["avatar_gender"] = directives.narrator  # plan-dependent field
        return payload
