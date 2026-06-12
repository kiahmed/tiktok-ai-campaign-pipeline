"""Domain-level exception hierarchy.

Providers translate their vendor-specific errors into these so the service and
API layers never have to know which vendor raised them.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for every error this application raises intentionally."""


class ConfigurationError(AppError):
    """A required setting is missing or invalid (e.g. no API key)."""


class ProviderError(AppError):
    """Base class for any failure that originates from an external provider."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}" if provider else message)


class ScriptGenerationError(ProviderError):
    """The script provider failed to produce a usable script."""


class VideoGenerationError(ProviderError):
    """The video provider failed to produce / deliver a video."""


class VoiceGenerationError(ProviderError):
    """The voice (TTS) provider failed to produce audio."""


class ImageGenerationError(ProviderError):
    """The image provider failed to produce an image."""


class QcRejectedError(AppError):
    """A script failed pre-video quality review — no video was generated."""

    def __init__(self, reasons=None, codes=None) -> None:
        self.reasons = list(reasons or [])
        self.codes = list(codes or [])
        detail = "; ".join(self.reasons) if self.reasons else "rejected by quality review"
        super().__init__(f"Script rejected by QC: {detail}")


class AdPlatformError(ProviderError):
    """The advertising platform rejected or failed a request."""


class StorageError(AppError):
    """Downloading or persisting a video artefact failed."""


class NotFoundError(AppError):
    """A requested domain entity does not exist."""
