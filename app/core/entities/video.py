from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class VideoSpec:
    """Platform delivery spec the Quality Review gate enforces on the output."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    allowed_formats: tuple[str, ...] = ("mp4", "mov")
    max_file_mb: float = 72.0
    check_media: bool = False  # deep-verify resolution/fps via ffprobe


@dataclass(slots=True)
class VideoResult:
    """A generated video, returned by any VideoGenerator.

    The provider returns a remote ``download_url`` (and optionally its own job
    id); the application is responsible for downloading and storing it locally.
    """

    download_url: str
    provider: str
    external_job_id: str | None = None
    format: str = "mp4"
    aspect_ratio: str = "9:16"
    duration_seconds: float | None = None
    # Full audit trail of the provider API calls made to produce this video
    # (selection, list, submit, status). Each item is a JSON-able dict. Persisted
    # per video so the exact payload + parameters can be reviewed later.
    api_calls: list[dict] = field(default_factory=list)
