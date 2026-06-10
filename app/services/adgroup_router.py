"""Chooses the ad group to publish a new video ad into.

Rules (in order):
  1. All ads go into the LATEST cloned campaign. Before any campaign is cloned,
     fall back to the configured default ad group (the template).
  2. If that campaign has exactly ONE ad group, use it.
  3. Otherwise, match the script's audience segment to an ad group by name
     (loose, token-based) — e.g. segment ``young_men_confidence`` -> an ad group
     named "Young Men - Confidence".
  4. No match -> the first ad group (stable fallback).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.repositories import AdGroupRepository, CampaignRepository

logger = logging.getLogger("service.adgroup_router")


@dataclass(slots=True)
class Route:
    adgroup_id: str
    campaign_id: str

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def _matches(segment: str, adgroup_name: str) -> bool:
    """Loose match: do the segment's tokens substantially overlap the name's?"""
    seg, name = _tokens(segment), _tokens(adgroup_name)
    if not seg or not name:
        return False
    overlap = len(seg & name)
    # Match if all segment tokens are present, or at least half overlap.
    return seg <= name or overlap >= max(1, (len(seg) + 1) // 2)


class AdGroupRouter:
    def __init__(
        self,
        *,
        campaign_repo: CampaignRepository,
        adgroup_repo: AdGroupRepository,
        default_adgroup_id: str,
        default_campaign_id: str,
    ) -> None:
        self._campaign_repo = campaign_repo
        self._adgroup_repo = adgroup_repo
        self._default_adgroup = default_adgroup_id
        self._default_campaign = default_campaign_id

    def select(self, audience_segment: str | None) -> Route:
        latest = self._campaign_repo.latest()
        if latest is None:
            return Route(self._default_adgroup, self._default_campaign)  # template default

        campaign_id = latest.platform_campaign_id
        adgroups = self._adgroup_repo.list_for_campaign(campaign_id)
        if not adgroups:
            return Route(self._default_adgroup, self._default_campaign)
        if len(adgroups) == 1:
            return Route(adgroups[0].platform_adgroup_id, campaign_id)

        if audience_segment:
            for ag in adgroups:
                if _matches(audience_segment, ag.name):
                    logger.info("Routed segment '%s' -> ad group '%s'", audience_segment, ag.name)
                    return Route(ag.platform_adgroup_id, campaign_id)

        logger.info("No ad-group match for segment '%s'; using first", audience_segment)
        return Route(adgroups[0].platform_adgroup_id, campaign_id)
