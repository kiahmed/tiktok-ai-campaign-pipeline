"""② Video Production Agent — turns the script candidate into a video candidate.

Paths:
  * provider produces_audio (e.g. HeyGen) — the provider returns a finished,
    voiced, lip-synced avatar video from the script alone. CREATIVE_MODE is
    ignored and no ElevenLabs/merge/lip-sync runs.
  * CREATIVE_MODE=product      — Kling image2video animates the product image;
    the ElevenLabs voiceover is merged on with ffmpeg (no lip-sync).
  * CREATIVE_MODE=talking_head — Kling text2video makes a person, then Kling
    lip-sync syncs their mouth to the ElevenLabs voiceover.
The Kling paths fall back gracefully (silent video) if voice/merge is missing.
"""
from __future__ import annotations

import logging
import os

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
        api_call_repo=None,
        storyboard=None,
        product_cutaway=None,
        captions=None,
        creative_mode: str = "product",
    ) -> None:
        self._gen = video_generator
        self._storage = storage
        self._product_repo = product_repo
        self._script_repo = script_repo
        self._video_repo = video_repo
        self._api_calls = api_call_repo
        self._storyboard = storyboard
        self._cutaway = product_cutaway
        self._captions = captions
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

        video = None
        if getattr(self._gen, "produces_audio", False):
            # Provider (e.g. HeyGen) returns a FINISHED, voiced, lip-synced video
            # from the script alone — no ElevenLabs voiceover / merge / lip-sync.
            video = self._gen.generate(product_input, script, directives)
            file_name = video_filename(slug)
            local_path = self._storage.download(video.download_url, file_name)
            # Optional post-step: compose a multi-scene STORY (b-roll under VO).
            if self._storyboard is not None:
                st = self._storyboard.apply(
                    local_path, script_text=script.text, duration_seconds=video.duration_seconds,
                )
                if st.path != local_path:
                    local_path, file_name = st.path, os.path.basename(st.path)
                if video is not None and st.logs:
                    video.api_calls.extend(st.logs)
            # Optional post-step: briefly cut to a full-screen product shot.
            if self._cutaway is not None:
                cut = self._cutaway.apply(
                    local_path, product=product_input, script_text=script.text,
                    duration_seconds=video.duration_seconds,
                )
                if cut.path != local_path:
                    local_path, file_name = cut.path, os.path.basename(cut.path)
                if cut.log:  # record the cutaway in the video's API-call log
                    video.api_calls.append(cut.log)
            # Optional post-step: burn captions (subtitles) from the script.
            if self._captions is not None:
                cc = self._captions.apply(
                    local_path, script_text=script.text, duration_seconds=video.duration_seconds,
                )
                if cc.path != local_path:
                    local_path, file_name = cc.path, os.path.basename(cc.path)
                if cc.log:
                    video.api_calls.append(cc.log)
            row = self._video_repo.create(
                product_id=job.product_id, script_id=script_row.id, provider=video.provider,
                external_job_id=video.external_job_id, remote_url=video.download_url,
                local_path=local_path, file_name=file_name, aspect_ratio=video.aspect_ratio,
                format=video.format, duration_seconds=video.duration_seconds,
            )
        elif self._creative_mode == "talking_head":
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

        # Persist the provider API-call audit trail (payload + params) for this video.
        if self._api_calls is not None and video is not None and video.api_calls:
            try:
                self._api_calls.record_many(row.id, video.api_calls)
            except Exception:  # auditing must never fail the pipeline
                logger.warning("Failed to store API-call history for video %s", row.id, exc_info=True)

        logger.info("Video candidate ready (%s mode): %s", self._creative_mode, row.local_path)
        return AgentResult(ok=True, next_status=JobStatus.VIDEO_READY, updates={"video_id": row.id})
