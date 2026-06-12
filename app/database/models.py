"""SQLAlchemy ORM models — the persistent schema.

Tables: products, scripts, videos, ads, metrics. Relationships are wired with
back-populated references and cascade deletes so the object graph stays
consistent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    FAILED = "FAILED"


class JobStatus(str, Enum):
    """Lifecycle of a creative job moving through the agent pipeline."""

    DRAFT = "DRAFT"              # created, awaiting Creative Strategist
    SCRIPTED = "SCRIPTED"        # script candidate ready, awaiting script QC
    SCRIPT_APPROVED = "SCRIPT_APPROVED"  # script passed QC, awaiting Video Production
    VIDEO_READY = "VIDEO_READY"  # video candidate ready, awaiting video QC
    APPROVED = "APPROVED"        # QC passed, awaiting TikTok Ad agent
    REJECTED = "REJECTED"        # QC failed (reason saved); will retry or discard
    LIVE = "LIVE"                # ad created on platform; Performance agent monitors
    DISCARDED = "DISCARDED"      # exhausted retry attempts after rejections
    FAILED = "FAILED"            # unexpected error during a stage


class QcVerdict(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    benefits: Mapped[str] = mapped_column(Text, default="")  # newline-joined
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    scripts: Mapped[list["Script"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    videos: Mapped[list["Video"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    ads: Mapped[list["Ad"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)  # spoken voiceover
    visual_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)  # video scene prompt
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # Strategist metadata (populated by the Creative Strategist agent).
    hook_type: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    angle: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    audience_segment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Cached embedding vector (JSON-encoded floats) for semantic novelty checks.
    # Null when the lexical novelty method is used (no vector needed).
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    product: Mapped["Product"] = relationship(back_populates="scripts")
    videos: Mapped[list["Video"]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    external_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255))
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16")
    format: Mapped[str] = mapped_column(String(10), default="mp4")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    product: Mapped["Product"] = relationship(back_populates="videos")
    script: Mapped["Script"] = relationship(back_populates="videos")
    ads: Mapped[list["Ad"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    api_calls: Mapped[list["VideoApiCall"]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="VideoApiCall.seq"
    )


class VideoApiCall(Base):
    """Audit trail of every provider API call made to generate a video.

    One row per call (selection, list, submit, status). Stores the exact request
    payload + resolved parameters and a compact response so the full history of a
    video's generation can be reviewed later.
    """

    __tablename__ = "video_api_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)  # order within the generation
    provider: Mapped[str] = mapped_column(String(50))
    method: Mapped[str] = mapped_column(String(10))       # POST | GET | SELECT
    endpoint: Mapped[str] = mapped_column(String(255))
    request_payload: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)     # JSON
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    video: Mapped["Video"] = relationship(back_populates="api_calls")


class Ad(Base):
    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )

    platform: Mapped[str] = mapped_column(String(50))
    campaign_id: Mapped[str] = mapped_column(String(255))
    adgroup_id: Mapped[str] = mapped_column(String(255))

    platform_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creative_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ad_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[AdStatus] = mapped_column(
        SAEnum(AdStatus), default=AdStatus.ACTIVE, index=True
    )
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    product: Mapped["Product"] = relationship(back_populates="ads")
    video: Mapped["Video"] = relationship(back_populates="ads")
    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="ad", cascade="all, delete-orphan", order_by="Metric.captured_at"
    )


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ad_id: Mapped[int] = mapped_column(
        ForeignKey("ads.id", ondelete="CASCADE"), index=True
    )

    spend: Mapped[float] = mapped_column(Float, default=0.0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    conversions: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)

    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    cpc: Mapped[float] = mapped_column(Float, default=0.0)
    cpa: Mapped[float] = mapped_column(Float, default=0.0)
    roas: Mapped[float] = mapped_column(Float, default=0.0)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, index=True
    )

    ad: Mapped["Ad"] = relationship(back_populates="metrics")


class PreviewRun(Base):
    """A stored dry-run preview (no media generated, nothing submitted).

    Captures the generated script, the assembled video API payload, the
    background scene prompt and the full dry-run audit trail so previews can be
    reviewed/compared on the dashboard before committing to generation.
    """

    __tablename__ = "preview_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    product_name: Mapped[str] = mapped_column(String(255), default="")
    provider: Mapped[str] = mapped_column(String(50), default="")
    script_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class CreativeJob(Base):
    """One unit of work flowing through the agent pipeline (the state machine)."""

    __tablename__ = "creative_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus), default=JobStatus.DRAFT, index=True
    )

    # Artifacts produced as the job advances (nullable until each stage runs).
    script_id: Mapped[int | None] = mapped_column(
        ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    ad_id: Mapped[int | None] = mapped_column(
        ForeignKey("ads.id", ondelete="SET NULL"), nullable=True
    )

    # Run options / control.
    prepared_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_to_platform: Mapped[bool] = mapped_column(default=True)
    # Target campaign / ad group for the ad (None => configured defaults).
    target_campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_adgroup_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    discard_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    product: Mapped["Product"] = relationship()
    qc_reviews: Mapped[list["QcReview"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="QcReview.created_at"
    )


class Campaign(Base):
    """A campaign created/cloned on the platform (we now manage these)."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(50))
    platform_campaign_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    template_campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AdGroup(Base):
    """An ad group created/cloned on the platform under a campaign."""

    __tablename__ = "ad_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(50))
    platform_adgroup_id: Mapped[str] = mapped_column(String(255), index=True)
    platform_campaign_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    template_adgroup_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class QcReview(Base):
    """A Quality Review verdict — the Knowledge the Strategist learns from."""

    __tablename__ = "qc_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("creative_jobs.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    script_id: Mapped[int | None] = mapped_column(
        ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )

    verdict: Mapped[QcVerdict] = mapped_column(SAEnum(QcVerdict), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[str] = mapped_column(Text, default="")  # human-readable, newline-joined
    failure_codes: Mapped[str] = mapped_column(Text, default="")  # comma-joined codes
    reviewer: Mapped[str] = mapped_column(String(50), default="rules")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    job: Mapped["CreativeJob"] = relationship(back_populates="qc_reviews")
