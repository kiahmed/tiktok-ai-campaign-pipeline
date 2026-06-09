from __future__ import annotations

from sqlalchemy import select

from app.database.models import Ad, AdStatus
from app.repositories.base import BaseRepository


class AdRepository(BaseRepository):
    def create(
        self,
        *,
        product_id: int,
        video_id: int,
        platform: str,
        campaign_id: str,
        adgroup_id: str,
        platform_video_id: str | None,
        creative_id: str | None,
        ad_id: str | None,
        name: str,
        status: AdStatus = AdStatus.ACTIVE,
    ) -> Ad:
        with self._unit_of_work() as session:
            ad = Ad(
                product_id=product_id,
                video_id=video_id,
                platform=platform,
                campaign_id=campaign_id,
                adgroup_id=adgroup_id,
                platform_video_id=platform_video_id,
                creative_id=creative_id,
                ad_id=ad_id,
                name=name,
                status=status,
            )
            session.add(ad)
            session.flush()
            session.refresh(ad)
            session.expunge(ad)
            return ad

    def get(self, pk: int) -> Ad | None:
        with self._unit_of_work() as session:
            ad = session.get(Ad, pk)
            if ad is not None:
                session.expunge(ad)
            return ad

    def list_active(self) -> list[Ad]:
        """All ads currently ACTIVE and successfully created on the platform."""
        with self._unit_of_work() as session:
            stmt = select(Ad).where(
                Ad.status == AdStatus.ACTIVE, Ad.ad_id.is_not(None)
            )
            ads = list(session.scalars(stmt).all())
            for ad in ads:
                session.expunge(ad)
            return ads

    def list_all(self) -> list[Ad]:
        with self._unit_of_work() as session:
            ads = list(session.scalars(select(Ad).order_by(Ad.created_at.desc())).all())
            for ad in ads:
                session.expunge(ad)
            return ads

    def mark_paused(self, pk: int, reason: str) -> None:
        with self._unit_of_work() as session:
            ad = session.get(Ad, pk)
            if ad is not None:
                ad.status = AdStatus.PAUSED
                ad.pause_reason = reason
