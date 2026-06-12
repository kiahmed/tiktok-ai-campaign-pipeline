"""Provider factories: map a configuration string to a concrete implementation.

This is the single place that knows the registry of providers. Everything else
depends on the abstract interface. Add a new provider by implementing the
interface and adding one line to the relevant registry below.
"""
from __future__ import annotations

from app.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.interfaces import AdPlatform, ScriptGenerator, VideoGenerator

# --- Script providers ---
from app.providers.gemini import GeminiScriptProvider
from app.providers.openai import OpenAIScriptProvider
from app.providers.claude import ClaudeScriptProvider

# --- Video providers ---
from app.providers.veo import VeoVideoProvider
from app.providers.pexo import PexoVideoProvider
from app.providers.creatify import CreatifyVideoProvider
from app.providers.arcads import ArcadsVideoProvider
from app.providers.kling import KlingVideoProvider
from app.providers.heygen import HeyGenVideoProvider

# --- Ad platform (TikTok only) ---
from app.providers.tiktok import TikTokAdPlatform


def _build_llm(provider: str, settings: Settings) -> ScriptGenerator:
    """Build an LLM provider (also usable as an LLMProvider transport)."""
    provider = provider.lower()
    if provider == "gemini":
        return GeminiScriptProvider(settings.gemini_api_key, settings.gemini_model)
    if provider == "openai":
        return OpenAIScriptProvider(settings.openai_api_key, settings.openai_model)
    if provider == "claude":
        return ClaudeScriptProvider(settings.claude_api_key, settings.claude_model)
    raise ConfigurationError(f"Unknown LLM provider='{provider}'")


def build_script_generator(settings: Settings) -> ScriptGenerator:
    return _build_llm(settings.script_provider, settings)


def build_qc_llm(settings: Settings) -> ScriptGenerator:
    """LLM used by the Quality Review judge. Defaults to the script provider."""
    return _build_llm(settings.qc_provider or settings.script_provider, settings)


def build_video_spec(settings: Settings):
    """Platform delivery spec enforced by Quality Review."""
    from app.core.entities.video import VideoSpec

    formats = tuple(
        x.strip().lower() for x in settings.video_formats.split(",") if x.strip()
    ) or ("mp4",)
    return VideoSpec(
        width=settings.video_width,
        height=settings.video_height,
        fps=settings.video_fps,
        allowed_formats=formats,
        max_file_mb=settings.video_max_file_mb,
        check_media=settings.video_check_media,
    )


def build_novelty_checker(settings: Settings):
    """Build the script de-duplication checker chosen by NOVELTY_METHOD."""
    from app.services.strategy import EmbeddingNovelty, LexicalNovelty

    method = settings.novelty_method.lower()
    if method == "lexical":
        return LexicalNovelty(threshold=settings.novelty_threshold or 0.5)
    if method == "embedding":
        # Imported here so the heavy local-model dependency is only required
        # when the embedding method is actually selected.
        from app.services.strategy.embeddings import LocalEmbedder

        return EmbeddingNovelty(
            LocalEmbedder(settings.embedding_model),
            threshold=settings.novelty_threshold or 0.85,
        )
    raise ConfigurationError(
        f"Unknown NOVELTY_METHOD='{settings.novelty_method}' (use 'lexical' or 'embedding')"
    )


def build_image_generator(settings: Settings):
    """Build the image generator (for HeyGen script-generated backgrounds), or
    None if disabled/unconfigured (so the pipeline degrades to no background)."""
    provider = (settings.image_provider or "").lower()
    if provider in ("", "none"):
        return None
    if provider in ("gemini", "imagen"):
        from app.providers.gemini import GeminiImageProvider

        if not settings.gemini_api_key:
            return None
        return GeminiImageProvider(
            settings.gemini_api_key,
            settings.imagen_model,
            retries_429=settings.imagen_max_retries_429,
            retry_wait=settings.imagen_retry_wait_seconds,
        )
    raise ConfigurationError(f"Unknown IMAGE_PROVIDER='{settings.image_provider}'")


def build_music_provider(settings: Settings):
    """Build the background-music provider, or None if disabled/unconfigured."""
    if not settings.music_enabled:
        return None
    provider = (settings.music_provider or "").lower()
    if provider == "jamendo":
        if not settings.jamendo_client_id:
            return None
        from app.providers.jamendo import JamendoMusicProvider

        return JamendoMusicProvider(
            settings.jamendo_client_id,
            base_url=settings.jamendo_base_url,
            query=settings.music_query,
            limit=settings.music_limit,
            commercial_only=settings.music_commercial_only,
        )
    raise ConfigurationError(f"Unknown MUSIC_PROVIDER='{settings.music_provider}'")


def build_video_generator(settings: Settings) -> VideoGenerator:
    provider = settings.video_provider.lower()
    if provider == "veo":
        return VeoVideoProvider(
            api_key=settings.veo_api_key or settings.gemini_api_key,
            model=settings.veo_model,
            base_url=settings.veo_base_url,
            resolution=settings.veo_resolution,
        )
    if provider == "pexo":
        return PexoVideoProvider(settings.pexo_api_key, settings.pexo_base_url)
    if provider == "creatify":
        return CreatifyVideoProvider(settings.creatify_api_key, "https://api.creatify.ai")
    if provider == "arcads":
        return ArcadsVideoProvider(settings.arcads_api_key, "https://api.arcads.ai")
    if provider == "kling":
        return KlingVideoProvider(
            access_key=settings.kling_access_key,
            secret_key=settings.kling_secret_key,
            api_key=settings.kling_api_key,
            base_url=settings.kling_base_url,
            model=settings.kling_model,
            duration=settings.kling_duration,
            mode=settings.kling_mode,
            prepare_image=settings.kling_prepare_image,
            image_width=settings.video_width,
            image_height=settings.video_height,
        )
    if provider == "heygen":
        # Story mode generates its own b-roll scenes; the avatar background is
        # then mostly hidden, so skip it to save Imagen quota (one less call).
        bg_mode = settings.heygen_background_mode
        if settings.story_mode_enabled and bg_mode == "script":
            bg_mode = "none"
        # Cast the avatar per script with the same LLM as SCRIPT_PROVIDER.
        need_llm = settings.heygen_smart_avatar or bg_mode == "script"
        llm = build_script_generator(settings) if need_llm else None
        # Image generator only needed for script-generated backgrounds.
        image_gen = build_image_generator(settings) if bg_mode == "script" else None
        return HeyGenVideoProvider(
            api_key=settings.heygen_api_key,
            avatar_id=settings.heygen_avatar_id,
            voice_id=settings.heygen_voice_id,
            image_url=settings.heygen_image_url,
            prefer_gender=settings.heygen_prefer_gender,
            llm=llm,
            smart_avatar=settings.heygen_smart_avatar,
            max_avatar_candidates=settings.heygen_max_avatar_candidates,
            avatar_pool=settings.heygen_avatar_pool,
            base_url=settings.heygen_base_url,
            engine=settings.heygen_engine,
            width=settings.video_width,
            height=settings.video_height,
            resolution=settings.heygen_resolution,
            aspect_ratio=settings.heygen_aspect_ratio,
            speed=settings.heygen_speed,
            remove_background=settings.heygen_remove_background,
            image_generator=image_gen,
            background_mode=bg_mode,
            background=settings.heygen_background,
        )
    raise ConfigurationError(f"Unknown VIDEO_PROVIDER='{settings.video_provider}'")


def build_voice_generator(settings: Settings):
    """Build the voiceover provider, or None if voice is disabled/unconfigured
    (so the pipeline degrades gracefully to a silent video)."""
    if not settings.voice_enabled:
        return None
    provider = settings.voice_provider.lower()
    if provider == "elevenlabs":
        if not (settings.elevenlabs_api_key and settings.elevenlabs_voice_id):
            return None  # enabled but not configured -> skip voice
        from app.providers.elevenlabs import ElevenLabsVoiceProvider

        return ElevenLabsVoiceProvider(
            settings.elevenlabs_api_key,
            settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model,
            base_url=settings.elevenlabs_base_url,
            storage_dir=settings.video_storage_dir,
        )
    raise ConfigurationError(f"Unknown VOICE_PROVIDER='{settings.voice_provider}'")


def build_ad_platform(settings: Settings) -> AdPlatform:
    platform = settings.ad_platform.lower()
    if platform == "tiktok":
        from app.providers.tiktok.token_manager import TikTokTokenManager

        token_manager = TikTokTokenManager(
            app_id=settings.tiktok_app_id,
            secret=settings.tiktok_app_secret,
            access_token=settings.tiktok_access_token,
            refresh_token=settings.tiktok_refresh_token,
            expires_at=settings.tiktok_token_expires_at,
            base_url=settings.tiktok_base_url,
            store_path=settings.tiktok_token_store,
        )
        return TikTokAdPlatform(
            token_manager=token_manager,
            advertiser_id=settings.tiktok_advertiser_id,
            campaign_id=settings.tiktok_campaign_id,
            adgroup_id=settings.tiktok_adgroup_id,
            base_url=settings.tiktok_base_url,
        )
    raise ConfigurationError(
        f"Unsupported AD_PLATFORM='{settings.ad_platform}'. Only 'tiktok' is supported."
    )


def active_campaign_id(settings: Settings) -> str:
    return settings.tiktok_campaign_id


def active_adgroup_id(settings: Settings) -> str:
    return settings.tiktok_adgroup_id
