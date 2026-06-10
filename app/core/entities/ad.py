from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UploadedVideo:
    """Result of uploading a local video file to the ad platform."""

    platform_video_id: str
    provider: str


@dataclass(slots=True)
class CampaignResult:
    """Identifiers returned after creating/cloning a campaign."""

    campaign_id: str
    name: str
    provider: str


@dataclass(slots=True)
class AdGroupResult:
    """Identifiers returned after creating/cloning an ad group."""

    adgroup_id: str
    campaign_id: str
    name: str
    provider: str


@dataclass(slots=True)
class AdGroupRef:
    """A lightweight reference to an existing ad group (id + name)."""

    adgroup_id: str
    name: str


@dataclass(slots=True)
class AdCreativeResult:
    """Identifiers returned after creating a creative + ad on the platform.

    Returned by the ad platform (TikTok) after creating the creative + ad.
    """

    platform_video_id: str
    creative_id: str
    ad_id: str
    provider: str
