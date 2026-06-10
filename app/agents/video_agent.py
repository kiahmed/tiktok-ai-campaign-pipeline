"""② Video Production Agent — turns the script candidate into a video candidate.

Two creative modes (CREATIVE_MODE):
  * product      — Kling image2video animates the product image; the ElevenLabs
                   voiceover is merged on with ffmpeg (no lip-sync).
  * talking_head — Kling text2video makes a person, then Kling lip-sync syncs
                   their mouth to the ElevenLabs voiceover.
Both fall back gracefully (silent video) if voice/merge is unavailable.
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
from app.services.talking_head import TalkingHeadProducer
from app.services.video_storage import VideoStorageService
from app.services.voiceover import VoiceoverService

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
        voiceover: VoiceoverService,
        talking_head: TalkingHeadProducer,
        creative_mode: str = "product",
    ) -> None:
        self._gen = video_generator
        self._storage = storage
        self._product_repo = product_repo
        self._script_repo = script_repo
        self._video_repo = video_repo
        self._profiles = profile_service
        self._voiceover = voiceover
        self._talking_head = talking_head
        self._creative_mode = creative_mode

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
            visual_prompt=script_row.visual_prompt,
        )
        directives = self._profiles.load().creative
        product_input = product_to_input(product)
        slug = slugify(product.name)

        if self._creative_mode == "talking_head":
            local_path, file_name, aspect, duration = self._talking_head.produce(
                product=product_input, script=script, directives=directives, slug=slug
            )
            row = self._video_repo.create(
                product_id=job.product_id, script_id=script_row.id, provider=self._gen.name,
                external_job_id=None, remote_url=None, local_path=local_path, file_name=file_name,
                aspect_ratio=aspect, format="mp4", duration_seconds=duration,
            )
        else:
            # product mode: image2video + voiceover merge
            video = self._gen.generate(product_input, script, directives)
            file_name = video_filename(slug)
            local_path = self._storage.download(video.download_url, file_name)
            local_path, file_name = self._voiceover.apply(
                slug=slug, video_path=local_path, file_name=file_name, text=script.text
            )
            row = self._video_repo.create(
                product_id=job.product_id, script_id=script_row.id, provider=video.provider,
                external_job_id=video.external_job_id, remote_url=video.download_url,
                local_path=local_path, file_name=file_name, aspect_ratio=video.aspect_ratio,
                format=video.format, duration_seconds=video.duration_seconds,
            )

        logger.info("Video candidate ready (%s mode): %s", self._creative_mode, row.local_path)
        return AgentResult(ok=True, next_status=JobStatus.VIDEO_READY, updates={"video_id": row.id})
