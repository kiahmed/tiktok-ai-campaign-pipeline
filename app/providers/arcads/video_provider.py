"""Arcads implementation of the VideoGenerator interface (drop-in for Pexo)."""
from __future__ import annotations

from app.core.entities import ProductInput, ScriptResult
from app.core.entities.profile import CreativeDirectives
from app.providers.base_video import PollingVideoProvider


class ArcadsVideoProvider(PollingVideoProvider):
    name = "arcads"
    create_path = "/api/v1/videos"
    status_path = "/api/v1/videos/{job_id}"

    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        payload = {
            "title": product.name,
            "script": script.text,
            "image_url": product.image_url,
            "ratio": "9:16",
        }
        if directives and directives.narrator:
            payload["actor_gender"] = directives.narrator  # plan-dependent field
        return payload
