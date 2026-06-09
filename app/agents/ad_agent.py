"""④ TikTok Ad Agent — posts the approved creative as an ad.

Constraint (unchanged): it ONLY uploads the video and creates an ad inside the
PRE-EXISTING campaign / ad group. It never creates or modifies campaigns or ad
groups. Ongoing pausing is handled by the scheduled monitor.
"""
from __future__ import annotations

import logging

from app.agents.base import Agent, AgentResult
from app.core.exceptions import NotFoundError
from app.database.models import AdStatus, CreativeJob, JobStatus
from app.repositories import AdRepository, ProductRepository, VideoRepository

logger = logging.getLogger("agent.ad")


class TikTokAdAgent(Agent):
    name = "tiktok_ad"

    def __init__(
        self,
        *,
        ad_platform,
        product_repo: ProductRepository,
        video_repo: VideoRepository,
        ad_repo: AdRepository,
        campaign_id: str,
        adgroup_id: str,
    ) -> None:
        self._ads = ad_platform
        self._product_repo = product_repo
        self._video_repo = video_repo
        self._ad_repo = ad_repo
        self._campaign_id = campaign_id
        self._adgroup_id = adgroup_id

    def run(self, job: CreativeJob) -> AgentResult:
        product = self._product_repo.get(job.product_id)
        video = self._video_repo.get(job.video_id) if job.video_id else None
        if product is None or video is None:
            raise NotFoundError("missing product or video for ad creation")

        ad_name = f"{product.name} - {video.file_name}"
        try:
            uploaded = self._ads.upload_video(video.local_path, file_name=video.file_name)
            result = self._ads.create_creative_and_ad(
                platform_video_id=uploaded.platform_video_id,
                ad_name=ad_name,
                landing_page_url=job.landing_page_url,
            )
        except Exception:
            # Record the failed attempt so it is visible, then let the
            # orchestrator mark the job FAILED.
            logger.exception("Ad creation failed for job %s", job.id)
            self._ad_repo.create(
                product_id=job.product_id,
                video_id=video.id,
                platform=self._ads.name,
                campaign_id=self._campaign_id,
                adgroup_id=self._adgroup_id,
                platform_video_id=None,
                creative_id=None,
                ad_id=None,
                name=ad_name,
                status=AdStatus.FAILED,
            )
            raise

        ad_row = self._ad_repo.create(
            product_id=job.product_id,
            video_id=video.id,
            platform=self._ads.name,
            campaign_id=self._campaign_id,
            adgroup_id=self._adgroup_id,
            platform_video_id=result.platform_video_id,
            creative_id=result.creative_id,
            ad_id=result.ad_id,
            name=ad_name,
            status=AdStatus.ACTIVE,
        )
        logger.info("Ad created ad_id=%s (job %s -> LIVE)", result.ad_id, job.id)
        return AgentResult(
            ok=True,
            next_status=JobStatus.LIVE,
            updates={"ad_id": ad_row.id},
            data={"ad_id": result.ad_id},
        )
