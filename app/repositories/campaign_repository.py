from __future__ import annotations

from sqlalchemy import select

from app.database.models import AdGroup, Campaign
from app.repositories.base import BaseRepository


class CampaignRepository(BaseRepository):
    def create(
        self, *, platform: str, platform_campaign_id: str, name: str, template_campaign_id: str | None
    ) -> Campaign:
        with self._unit_of_work() as session:
            row = Campaign(
                platform=platform,
                platform_campaign_id=platform_campaign_id,
                name=name,
                template_campaign_id=template_campaign_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def list_all(self) -> list[Campaign]:
        with self._unit_of_work() as session:
            rows = list(session.scalars(select(Campaign).order_by(Campaign.created_at.desc())).all())
            for r in rows:
                session.expunge(r)
            return rows

    def latest(self) -> Campaign | None:
        """The most recently created campaign (the current 'latest' campaign).

        Ordered by id as the tiebreaker so it is deterministic even when several
        campaigns share the same created_at second.
        """
        with self._unit_of_work() as session:
            row = session.scalars(
                select(Campaign)
                .order_by(Campaign.created_at.desc(), Campaign.id.desc())
                .limit(1)
            ).first()
            if row is not None:
                session.expunge(row)
            return row


class AdGroupRepository(BaseRepository):
    def create(
        self,
        *,
        platform: str,
        platform_adgroup_id: str,
        platform_campaign_id: str,
        name: str,
        template_adgroup_id: str | None,
    ) -> AdGroup:
        with self._unit_of_work() as session:
            row = AdGroup(
                platform=platform,
                platform_adgroup_id=platform_adgroup_id,
                platform_campaign_id=platform_campaign_id,
                name=name,
                template_adgroup_id=template_adgroup_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def list_all(self) -> list[AdGroup]:
        with self._unit_of_work() as session:
            rows = list(session.scalars(select(AdGroup).order_by(AdGroup.created_at.desc())).all())
            for r in rows:
                session.expunge(r)
            return rows

    def list_for_campaign(self, platform_campaign_id: str) -> list[AdGroup]:
        with self._unit_of_work() as session:
            stmt = (
                select(AdGroup)
                .where(AdGroup.platform_campaign_id == platform_campaign_id)
                .order_by(AdGroup.created_at.asc())
            )
            rows = list(session.scalars(stmt).all())
            for r in rows:
                session.expunge(r)
            return rows
