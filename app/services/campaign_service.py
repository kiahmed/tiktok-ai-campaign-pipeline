"""Campaign lifecycle: deep-clone a template and persist the result.

Deep clone = new campaign + a copy of each of the template's ad groups (no ads;
fresh ads are added later per video). Used both by the trigger endpoint and by
the scheduled clone job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.repositories import AdGroupRepository, CampaignRepository

logger = logging.getLogger("service.campaign")


@dataclass(slots=True)
class CloneOutcome:
    campaign: object              # Campaign row
    adgroups: list                # AdGroup rows


class CampaignService:
    def __init__(
        self,
        *,
        ad_platform,
        campaign_repo: CampaignRepository,
        adgroup_repo: AdGroupRepository,
        template_campaign_id: str,
    ) -> None:
        self._ads = ad_platform
        self._campaign_repo = campaign_repo
        self._adgroup_repo = adgroup_repo
        self._template_campaign_id = template_campaign_id

    def clone(
        self,
        *,
        name: str,
        template_campaign_id: str | None = None,
        clone_adgroups: bool = True,
        overrides: dict | None = None,
    ) -> CloneOutcome:
        template = template_campaign_id or self._template_campaign_id
        if not template:
            raise ValueError("no template campaign id (set TIKTOK_CAMPAIGN_ID)")

        camp = self._ads.clone_campaign(
            template_campaign_id=template, name=name, overrides=overrides
        )
        camp_row = self._campaign_repo.create(
            platform=camp.provider,
            platform_campaign_id=camp.campaign_id,
            name=camp.name,
            template_campaign_id=template,
        )
        logger.info("Cloned campaign %s (from template %s)", camp.campaign_id, template)

        adgroup_rows = []
        if clone_adgroups:
            for ref in self._ads.list_adgroups(template):
                ag = self._ads.create_adgroup(
                    campaign_id=camp.campaign_id,
                    name=ref.name or f"Ad group {ref.adgroup_id}",
                    template_adgroup_id=ref.adgroup_id,
                )
                ag_row = self._adgroup_repo.create(
                    platform=ag.provider,
                    platform_adgroup_id=ag.adgroup_id,
                    platform_campaign_id=camp.campaign_id,
                    name=ag.name,
                    template_adgroup_id=ref.adgroup_id,
                )
                adgroup_rows.append(ag_row)
            logger.info("Cloned %d ad group(s) into campaign %s", len(adgroup_rows), camp.campaign_id)

        return CloneOutcome(campaign=camp_row, adgroups=adgroup_rows)
