"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class ProductRequest(BaseModel):
    name: str = Field(..., examples=["Rosemary Hair Growth Oil"])
    # Optional: the product shot is picked at random from config/product_images.json.
    image_url: HttpUrl | None = Field(default=None, examples=["https://example.com/product.jpg"])
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


# ---- Campaign / ad-group management ----
class CloneCampaignRequest(BaseModel):
    name: str = Field(..., examples=["Pure Purc - June - Conversions"])
    template_campaign_id: str | None = Field(
        default=None, description="Campaign to clone. Defaults to TIKTOK_CAMPAIGN_ID."
    )
    clone_adgroups: bool = Field(
        default=True, description="Also clone the template's ad groups (deep clone)."
    )
    overrides: dict = Field(default_factory=dict, description="Fields to override on create.")


class CloneCampaignResponse(BaseModel):
    campaign: "CampaignOut"
    adgroups: list["AdGroupOut"]


class CampaignOut(BaseModel):
    id: int
    platform: str
    platform_campaign_id: str
    name: str
    template_campaign_id: str | None
    created_at: str


class CreateAdGroupRequest(BaseModel):
    campaign_id: str = Field(..., description="Platform campaign id to create the ad group under.")
    name: str = Field(..., examples=["Men 25-40 - Interest: Hair Care"])
    template_adgroup_id: str | None = Field(
        default=None, description="Ad group to clone settings from. Defaults to TIKTOK_ADGROUP_ID."
    )
    overrides: dict = Field(default_factory=dict, description="Fields to override (e.g. audience).")


class AdGroupOut(BaseModel):
    id: int
    platform: str
    platform_adgroup_id: str
    platform_campaign_id: str
    name: str
    template_adgroup_id: str | None
    created_at: str


class PreviewRequest(BaseModel):
    """Dry-run preview input: generate the script + assemble the exact video API
    payload WITHOUT generating media or submitting. Provide a product_id, or
    name (+ optional image_url/description/benefits)."""

    product_id: int | None = None
    name: str | None = None
    image_url: str | None = None
    description: str = ""
    benefits: list[str] = Field(default_factory=list)
    prepared_script: str | None = Field(
        default=None, description="Use this script verbatim instead of generating one."
    )


class PreviewResponse(BaseModel):
    id: int | None = None        # stored preview-run id (for history)
    provider: str | None = None
    script: dict                 # the script object (text, visual_prompt, hook/angle/...)
    scene_prompt: str | None = None   # background scene prompt (if background_mode=script)
    payload: dict                # the exact request that WOULD be sent to the video API
    calls: list[dict]            # full dry-run audit trail (script, selection, etc.)


class PreviewRunItem(BaseModel):
    """One row in the preview history list."""

    id: int
    product_id: int | None = None
    product_name: str
    provider: str
    created_at: str


class PreviewRunDetail(BaseModel):
    id: int
    product_id: int | None = None
    product_name: str
    provider: str
    created_at: str
    script: dict | None = None
    scene_prompt: str | None = None
    payload: dict | None = None
    calls: list[dict] = Field(default_factory=list)


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
    script: str               # spoken voiceover (ElevenLabs)
    visual_prompt: str | None  # what the video shows (Kling)
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
    target_campaign_id: str | None = Field(
        default=None, description="Publish the ad under this campaign (defaults to config)."
    )
    target_adgroup_id: str | None = Field(
        default=None, description="Publish the ad into this ad group (defaults to config)."
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
    visual_prompt: str | None = None
    word_count: int | None = None
    script_provider: str | None = None
    script_model: str | None = None
    video_id: int | None = None
    video_url: str | None = None
    ad_id: str | None = None
    last_qc_verdict: str | None = None
    last_qc_codes: list[str] = Field(default_factory=list)
    last_qc_reasons: list[str] = Field(default_factory=list)
    discard_reason: str | None = None
    created_at: str


class VideoApiCallOut(BaseModel):
    seq: int
    provider: str
    method: str
    endpoint: str
    request_payload: dict | list | None = None
    response_body: dict | list | None = None
    status_code: int | None = None
    created_at: str


class ApiCallLogItem(BaseModel):
    """One entry in the global API-call log (across all videos)."""

    id: int
    video_id: int
    seq: int
    provider: str
    method: str
    endpoint: str
    request_payload: dict | list | None = None
    response_body: dict | list | None = None
    status_code: int | None = None
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
