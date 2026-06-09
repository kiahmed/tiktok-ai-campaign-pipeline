"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class ProductRequest(BaseModel):
    name: str = Field(..., examples=["Rosemary Hair Growth Oil"])
    image_url: HttpUrl = Field(..., examples=["https://example.com/product.jpg"])
    description: str = Field(default="", examples=["A natural rosemary oil for hair."])
    benefits: list[str] = Field(
        default_factory=list,
        examples=[["Reduce hair shedding", "Promote thicker hair", "Natural ingredients"]],
    )
    landing_page_url: str | None = Field(
        default=None, description="Optional CTA landing page for the ad."
    )
    script: str | None = Field(
        default=None,
        description=(
            "Prepared ad script. When provided, the script generator (e.g. "
            "Gemini) is skipped and this text is used verbatim."
        ),
        examples=["Tired of thinning hair? I was too. Pure Purc Hair Oil "
                  "regrew mine in weeks. Tap to try it risk-free!"],
    )
    deploy: bool = Field(
        default=True,
        description=(
            "When false, stop after the video is generated and downloaded — no "
            "TikTok upload and no ad is created. Use for 'generate video only' tests."
        ),
    )


class ScriptGenRequest(BaseModel):
    """Script-only preview input. Provide product details, or a product_id to
    reuse an existing product's accumulated history (angles/rejections)."""

    product_id: int | None = Field(
        default=None, description="Reuse an existing product's history for context."
    )
    name: str | None = Field(default=None, examples=["Rosemary Hair Growth Oil"])
    description: str = ""
    benefits: list[str] = Field(default_factory=list)


class ScriptGenResponse(BaseModel):
    hook_type: str
    angle: str
    audience_segment: str | None
    script: str
    word_count: int
    mode: str          # exploit | explore
    similarity: float  # vs past scripts (lower = more novel)
    provider: str


class CreativeResponse(BaseModel):
    product_id: int
    script_id: int
    video_id: int
    script_text: str
    script_provider: str
    local_video_path: str
    deployed: bool
    # Present only when deployed to the ad platform.
    ad_row_id: int | None = None
    platform_video_id: str | None = None
    creative_id: str | None = None
    ad_id: str | None = None


class MonitoringRunResponse(BaseModel):
    evaluated: int
    paused: int
    errors: int
    paused_ad_ids: list[str]


class MetricOut(BaseModel):
    captured_at: str
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    ctr: float
    cpc: float
    cpa: float
    roas: float


class AdOut(BaseModel):
    id: int
    name: str
    platform: str
    status: str
    ad_id: str | None
    creative_id: str | None
    platform_video_id: str | None
    pause_reason: str | None


class HealthResponse(BaseModel):
    status: str
    script_provider: str
    video_provider: str
    ad_platform: str


# ---- Dashboard overview ----
class VideoInfo(BaseModel):
    file_name: str
    url: str | None = None  # served path for in-browser preview/download
    aspect_ratio: str
    duration_seconds: float | None = None
    provider: str


class OverviewItem(BaseModel):
    id: int
    name: str
    platform: str
    status: str
    ad_id: str | None
    creative_id: str | None
    platform_video_id: str | None
    pause_reason: str | None
    created_at: str
    video: VideoInfo | None = None
    latest_metrics: MetricOut | None = None
    measured_at: str | None = None


class OverviewSummary(BaseModel):
    total_ads: int
    active: int
    paused: int
    failed: int
    total_spend: float
    total_conversions: int
    avg_roas: float


class OverviewResponse(BaseModel):
    summary: OverviewSummary
    providers: HealthResponse
    ads: list[OverviewItem]


# ---- Agent pipeline / jobs ----
class JobRequest(BaseModel):
    # Either target an existing product (so the Strategist accumulates history
    # across jobs)...
    product_id: int | None = Field(
        default=None, description="Reuse an existing product instead of creating one."
    )
    # ...or describe a new product (used when product_id is omitted).
    name: str | None = Field(default=None, examples=["Pure Purc Hair Oil"])
    image_url: HttpUrl | None = Field(default=None, examples=["https://example.com/product.jpg"])
    description: str = ""
    benefits: list[str] = Field(default_factory=list)
    landing_page_url: str | None = None
    prepared_script: str | None = Field(
        default=None, description="Skip the Strategist and use this script."
    )
    post_to_platform: bool = Field(
        default=True, description="If false, stop at APPROVED (don't create the ad)."
    )


class QcReviewOut(BaseModel):
    verdict: str
    score: float
    reasons: list[str]
    failure_codes: list[str]
    reviewer: str
    attempt: int
    created_at: str


class JobResponse(BaseModel):
    id: int
    product_id: int
    status: str
    attempt: int
    max_attempts: int
    script_id: int | None = None
    video_id: int | None = None
    ad_id: int | None = None
    last_error: str | None = None
    discard_reason: str | None = None
    qc_reviews: list[QcReviewOut] = Field(default_factory=list)


# ---- Dashboard: jobs + strategy insights ----
class JobOverviewItem(BaseModel):
    id: int
    product_id: int
    product_name: str
    status: str
    attempt: int
    max_attempts: int
    angle: str | None = None
    hook_type: str | None = None
    audience_segment: str | None = None
    script_text: str | None = None
    video_url: str | None = None
    ad_id: str | None = None
    last_qc_verdict: str | None = None
    last_qc_codes: list[str] = Field(default_factory=list)
    last_qc_reasons: list[str] = Field(default_factory=list)
    discard_reason: str | None = None
    created_at: str


class AnglePerfOut(BaseModel):
    key: str
    count: int
    avg_ctr: float
    avg_roas: float
    score: float


class StrategyInsight(BaseModel):
    product_id: int
    product_name: str
    angle_performance: list[AnglePerfOut]
    hook_performance: list[AnglePerfOut]
    overused_angles: list[str]
    overused_hooks: list[str]
    recent_failure_codes: list[str]
    scripts_count: int
