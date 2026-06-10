from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.entities import AdCreativeResult, PerformanceMetrics
from app.core.entities.ad import AdGroupRef, AdGroupResult, CampaignResult, UploadedVideo


class AdPlatform(ABC):
    """Manages campaigns, ad groups, creatives and ads on an ad platform.

    Implementation: TikTok (the only supported ad platform).

    The platform can clone a campaign from a template and create ad groups
    under it; campaigns/ad groups are managed explicitly via triggerable
    operations (the caller controls cadence).
    """

    name: str = "abstract"

    @abstractmethod
    def clone_campaign(
        self, *, template_campaign_id: str, name: str, overrides: dict | None = None
    ) -> CampaignResult:
        """Create a new campaign by copying a template campaign's settings."""
        raise NotImplementedError

    @abstractmethod
    def list_adgroups(self, campaign_id: str) -> list[AdGroupRef]:
        """List the ad groups belonging to a campaign (for deep cloning)."""
        raise NotImplementedError

    @abstractmethod
    def create_adgroup(
        self,
        *,
        campaign_id: str,
        name: str,
        template_adgroup_id: str | None = None,
        overrides: dict | None = None,
    ) -> AdGroupResult:
        """Create an ad group under ``campaign_id``.

        When ``template_adgroup_id`` is given, the template's settings
        (targeting/budget/bid/schedule/...) are copied; otherwise ``overrides``
        must supply the required fields.
        """
        raise NotImplementedError

    @abstractmethod
    def upload_video(self, file_path: str, *, file_name: str) -> UploadedVideo:
        """Upload a local video file; return the platform's video id."""
        raise NotImplementedError

    @abstractmethod
    def create_creative_and_ad(
        self,
        *,
        platform_video_id: str,
        ad_name: str,
        adgroup_id: str | None = None,
        landing_page_url: str | None = None,
        call_to_action: str = "SHOP_NOW",
    ) -> AdCreativeResult:
        """Create a creative and an ad inside an ad group.

        ``adgroup_id`` targets a specific ad group; if omitted, the platform's
        default (configured) ad group is used. Returns video/creative/ad ids.
        """
        raise NotImplementedError

    @abstractmethod
    def get_ad_metrics(self, ad_id: str) -> PerformanceMetrics:
        """Fetch current performance metrics for an ad (normalised)."""
        raise NotImplementedError

    @abstractmethod
    def pause_ad(self, ad_id: str) -> None:
        """Pause a running ad. Must be idempotent."""
        raise NotImplementedError
