"""TikTok Marketing API implementation of the AdPlatform interface.

Scope of this provider — by design it ONLY:
  * uploads a video file                      (POST /file/video/ad/upload/)
  * creates a creative + ad in an EXISTING    (POST /ad/create/)
    ad group
  * reads ad performance metrics              (GET  /report/integrated/get/)
  * pauses an ad                              (POST /ad/status/update/)

It NEVER calls /campaign/create/ or /adgroup/create/. The campaign and ad group
must already exist and are supplied via configuration.

TikTok wraps every response as ``{"code": 0, "message": "OK", "data": {...}}``.
A non-zero ``code`` is an error, which we translate to ``AdPlatformError``.
"""
from __future__ import annotations

import hashlib
import logging
import os

import requests

from app.core.entities import AdCreativeResult, PerformanceMetrics
from app.core.entities.ad import UploadedVideo
from app.core.exceptions import AdPlatformError, ConfigurationError
from app.core.http import translate_network_errors
from app.core.interfaces import AdPlatform
from app.core.retry import with_retry
from app.providers.tiktok.token_manager import AUTH_ERROR_CODES, TikTokTokenManager

logger = logging.getLogger("provider.tiktok")


class TikTokAdPlatform(AdPlatform):
    name = "tiktok"

    def __init__(
        self,
        *,
        token_manager: "TikTokTokenManager",
        advertiser_id: str,
        campaign_id: str,
        adgroup_id: str,
        base_url: str = "https://business-api.tiktok.com/open_api/v1.3",
        timeout: int = 120,
    ) -> None:
        missing = [
            n
            for n, v in {
                "TIKTOK_ADVERTISER_ID": advertiser_id,
                "TIKTOK_ADGROUP_ID": adgroup_id,
            }.items()
            if not v
        ]
        if missing:
            raise ConfigurationError(f"TikTok config missing: {', '.join(missing)}")
        self._tokens = token_manager
        self._advertiser_id = advertiser_id
        self._campaign_id = campaign_id
        self._adgroup_id = adgroup_id
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def _token(self) -> str:
        """A currently-valid access token (auto-refreshed near expiry)."""
        return self._tokens.valid_token()

    # ------------------------------------------------------------------ #
    # Upload video
    # ------------------------------------------------------------------ #
    @translate_network_errors(AdPlatformError)
    @with_retry()
    def upload_video(self, file_path: str, *, file_name: str) -> UploadedVideo:
        if not os.path.exists(file_path):
            raise AdPlatformError(f"video file not found: {file_path}", provider=self.name)
        logger.info("Uploading video to TikTok: %s", file_name)
        with open(file_path, "rb") as fh:
            content = fh.read()
        signature = hashlib.md5(content).hexdigest()
        resp = requests.post(
            f"{self._base}/file/video/ad/upload/",
            headers={"Access-Token": self._token},
            data={
                "advertiser_id": self._advertiser_id,
                "upload_type": "UPLOAD_BY_FILE",
                "file_name": file_name,
                "video_signature": signature,
            },
            files={"video_file": (file_name, content, "video/mp4")},
            timeout=self._timeout,
        )
        data = self._unwrap(resp, action="upload_video")
        # data is a list of uploaded videos.
        first = data[0] if isinstance(data, list) else data
        video_id = first.get("video_id")
        if not video_id:
            raise AdPlatformError(f"no video_id in upload response: {data}", provider=self.name)
        logger.info("TikTok video uploaded video_id=%s", video_id)
        return UploadedVideo(platform_video_id=str(video_id), provider=self.name)

    # ------------------------------------------------------------------ #
    # Create creative + ad inside the existing ad group
    # ------------------------------------------------------------------ #
    @translate_network_errors(AdPlatformError)
    @with_retry()
    def create_creative_and_ad(
        self,
        *,
        platform_video_id: str,
        ad_name: str,
        landing_page_url: str | None = None,
        call_to_action: str = "SHOP_NOW",
    ) -> AdCreativeResult:
        logger.info("Creating TikTok ad '%s' in adgroup=%s", ad_name, self._adgroup_id)
        creative: dict = {
            "ad_name": ad_name,
            "identity_type": "CUSTOMIZED_USER",
            "video_id": platform_video_id,
            "ad_format": "SINGLE_VIDEO",
            "call_to_action": call_to_action,
            "ad_text": ad_name,
        }
        if landing_page_url:
            creative["landing_page_url"] = landing_page_url

        payload = {
            "advertiser_id": self._advertiser_id,
            # NOTE: we attach to the *existing* ad group; we do not create one.
            "adgroup_id": self._adgroup_id,
            "creatives": [creative],
        }
        resp = requests.post(
            f"{self._base}/ad/create/",
            headers={"Access-Token": self._token, "Content-Type": "application/json"},
            json=payload,
            timeout=self._timeout,
        )
        data = self._unwrap(resp, action="create_ad")
        ad_ids = data.get("ad_ids") or []
        creatives = data.get("creatives") or []
        ad_id = str(ad_ids[0]) if ad_ids else None
        creative_id = str(creatives[0].get("creative_id")) if creatives and creatives[0].get("creative_id") else ad_id
        if not ad_id:
            raise AdPlatformError(f"no ad_ids in create response: {data}", provider=self.name)
        logger.info("TikTok ad created ad_id=%s creative_id=%s", ad_id, creative_id)
        return AdCreativeResult(
            platform_video_id=platform_video_id,
            creative_id=creative_id or ad_id,
            ad_id=ad_id,
            provider=self.name,
        )

    # ------------------------------------------------------------------ #
    # Metrics
    # ------------------------------------------------------------------ #
    @translate_network_errors(AdPlatformError)
    @with_retry()
    def get_ad_metrics(self, ad_id: str) -> PerformanceMetrics:
        metrics = [
            "spend",
            "impressions",
            "clicks",
            "ctr",
            "cpc",
            "conversion",
            "cost_per_conversion",
            "total_complete_payment_rate",
            "complete_payment_roas",
            "total_complete_payment",
        ]
        params = {
            "advertiser_id": self._advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_AD",
            "dimensions": '["ad_id"]',
            "metrics": _json_list(metrics),
            "filters": _json_list(
                [{"field_name": "ad_ids", "filter_type": "IN", "filter_value": f'["{ad_id}"]'}]
            ),
        }
        resp = requests.get(
            f"{self._base}/report/integrated/get/",
            headers={"Access-Token": self._token},
            params=params,
            timeout=self._timeout,
        )
        data = self._unwrap(resp, action="get_metrics")
        rows = data.get("list") or []
        if not rows:
            logger.info("No report rows yet for ad_id=%s; returning zeros", ad_id)
            return PerformanceMetrics().with_derived()
        raw = rows[0].get("metrics", {})
        return self._map_metrics(raw)

    @staticmethod
    def _map_metrics(raw: dict) -> PerformanceMetrics:
        def num(key: str, cast=float, default=0):
            try:
                return cast(raw.get(key) or default)
            except (TypeError, ValueError):
                return default

        revenue = num("total_complete_payment", float)
        snapshot = PerformanceMetrics(
            spend=num("spend", float),
            impressions=num("impressions", int),
            clicks=num("clicks", int),
            conversions=num("conversion", int),
            revenue=revenue,
        )
        # TikTok already reports ctr/cpc/roas, but we recompute from primitives
        # so the values are internally consistent and always present.
        return snapshot.with_derived()

    # ------------------------------------------------------------------ #
    # Pause
    # ------------------------------------------------------------------ #
    @translate_network_errors(AdPlatformError)
    @with_retry()
    def pause_ad(self, ad_id: str) -> None:
        logger.info("Pausing TikTok ad_id=%s", ad_id)
        resp = requests.post(
            f"{self._base}/ad/status/update/",
            headers={"Access-Token": self._token, "Content-Type": "application/json"},
            json={
                "advertiser_id": self._advertiser_id,
                "ad_ids": [ad_id],
                "operation_status": "DISABLE",
            },
            timeout=self._timeout,
        )
        self._unwrap(resp, action="pause_ad")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _unwrap(self, resp: requests.Response, *, action: str):
        if resp.status_code >= 400:
            raise AdPlatformError(
                f"{action} HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        body = resp.json()
        code = body.get("code")
        if code not in (0, None):
            # Reactive: if the token was rejected, force a refresh next call.
            if code in AUTH_ERROR_CODES:
                logger.warning("TikTok auth error code=%s; invalidating token", code)
                self._tokens.invalidate()
            raise AdPlatformError(
                f"{action} code={code} msg={body.get('message')}",
                provider=self.name,
            )
        return body.get("data", {})


def _json_list(value) -> str:
    import json

    return json.dumps(value)
