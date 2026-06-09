from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.entities import AdCreativeResult, PerformanceMetrics
from app.core.entities.ad import UploadedVideo


class AdPlatform(ABC):
    """Manages creatives and ads on an advertising platform.

    Implementation: TikTok (the only supported ad platform).

    IMPORTANT: implementations MUST NOT create campaigns or ad groups. They
    operate strictly inside an *existing* campaign / ad group whose IDs are
    supplied via configuration.
    """

    name: str = "abstract"

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
        landing_page_url: str | None = None,
        call_to_action: str = "SHOP_NOW",
    ) -> AdCreativeResult:
        """Create a creative and an ad inside the pre-existing ad group.

        Returns the platform video id, creative id and ad id.
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
