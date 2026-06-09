"""Pexo AI implementation of the VideoGenerator interface.

Pexo generates video asynchronously (submit job -> poll status), which is
exactly what :class:`PollingVideoProvider` handles. This class only declares
Pexo's endpoints and payload shape.

NOTE: adjust ``create_path`` / ``status_path`` / payload keys to match your
exact Pexo plan if they differ — no other code needs to change.
"""
from __future__ import annotations

from app.core.entities import ProductInput, ScriptResult
from app.core.entities.profile import CreativeDirectives
from app.providers.base_video import PollingVideoProvider


class PexoVideoProvider(PollingVideoProvider):
    name = "pexo"
    create_path = "/v1/videos"
    status_path = "/v1/videos/{job_id}"

    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        payload = {
            "script": script.text,
            "image_url": product.image_url,
            "aspect_ratio": "9:16",
            "format": "mp4",
            "name": product.name,
        }
        # Apply tested creative cues. NOTE: these field names are plan-dependent —
        # confirm them against your Pexo create-video API and rename as needed.
        # If Pexo ignores unknown fields, harmless; if it rejects them, drop here
        # and instead set presenter/music in your Pexo template.
        if directives:
            if directives.narrator:
                payload["avatar_gender"] = directives.narrator          # e.g. "male"
            if directives.music:
                payload["background_music"] = directives.music          # music style/brief
            if directives.format:
                payload["style"] = directives.format                    # creative format
        return payload
