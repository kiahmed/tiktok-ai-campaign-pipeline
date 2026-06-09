"""② Video Production Agent — turns the script candidate into a video candidate.

Wraps the existing VideoGenerator + VideoStorageService (download to
generated_videos/). No business logic changes — it just operates within the
job state machine.
"""
from __future__ import annotations

import logging

from app.agents.base import Agent, AgentResult, product_to_input
from app.core.entities import ScriptResult
from app.core.exceptions import NotFoundError
from app.database.models import CreativeJob, JobStatus
from app.repositories import ProductRepository, ScriptRepository, VideoRepository
from app.services.naming import slugify, video_filename
from app.services.profile_service import ProfileService
from app.services.video_storage import VideoStorageService

logger = logging.getLogger("agent.video")


class VideoProductionAgent(Agent):
    name = "video_production"

    def __init__(
        self,
        *,
        video_generator,
        storage: VideoStorageService,
        product_repo: ProductRepository,
        script_repo: ScriptRepository,
        video_repo: VideoRepository,
        profile_service: ProfileService,
    ) -> None:
        self._gen = video_generator
        self._storage = storage
        self._product_repo = product_repo
        self._script_repo = script_repo
        self._video_repo = video_repo
        self._profiles = profile_service

    def run(self, job: CreativeJob) -> AgentResult:
        product = self._product_repo.get(job.product_id)
        script_row = self._script_repo.get(job.script_id) if job.script_id else None
        if product is None or script_row is None:
            raise NotFoundError("missing product or script for video production")

        script = ScriptResult(
            text=script_row.text,
            provider=script_row.provider,
            model=script_row.model,
            word_count=script_row.word_count,
        )
        directives = self._profiles.load().creative
        video = self._gen.generate(product_to_input(product), script, directives)

        file_name = video_filename(slugify(product.name))
        local_path = self._storage.download(video.download_url, file_name)
        row = self._video_repo.create(
            product_id=job.product_id,
            script_id=script_row.id,
            provider=video.provider,
            external_job_id=video.external_job_id,
            remote_url=video.download_url,
            local_path=local_path,
            file_name=file_name,
            aspect_ratio=video.aspect_ratio,
            format=video.format,
            duration_seconds=video.duration_seconds,
        )
        logger.info("Video candidate ready: %s", local_path)
        return AgentResult(
            ok=True,
            next_status=JobStatus.VIDEO_READY,
            updates={"video_id": row.id},
        )
