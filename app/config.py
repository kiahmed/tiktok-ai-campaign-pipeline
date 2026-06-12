"""Centralised, type-safe configuration loaded from environment / .env.

Everything the application needs to run is expressed here as a pydantic
``Settings`` object. Provider selection lives here too, which is what makes
"switch providers by editing .env only" possible: the DI container reads these
string keys and resolves the matching implementation.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read (in order of precedence) from real environment variables,
    then from a local ``.env`` file. Unknown keys are ignored so the same
    ``.env`` can carry credentials for providers that are not currently active.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Application ----
    app_name: str = "tiktok-ad-automator"
    log_level: str = "INFO"
    video_storage_dir: str = "generated_videos"

    # ---- Database ----
    database_url: str = "sqlite:///./app.db"

    # ---- Provider selection (the only thing you change to swap a provider) ----
    script_provider: str = "gemini"
    video_provider: str = "kling"
    ad_platform: str = "tiktok"  # TikTok is the only supported ad platform
    # Creative style:
    #   product      = image2video animates the product image + voiceover (no lip-sync)
    #   talking_head = text2video person + Kling lip-sync to the ElevenLabs voice
    creative_mode: str = "product"
    # Quality Review judge LLM. Empty => reuse SCRIPT_PROVIDER. Options: gemini|openai|claude
    qc_provider: str = ""
    # Run the LLM QC judge on top of the deterministic rules.
    qc_llm_enabled: bool = True

    # ---- Script providers ----
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # ---- Video providers ----
    # Veo 3.1 via the Gemini API (default). Reuses GEMINI_API_KEY if VEO_API_KEY is unset.
    veo_api_key: str = ""
    veo_model: str = "veo-3.1-generate-preview"
    veo_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # 9:16 @ 1080p => 1080x1920 (TikTok/Reels). Options: 720p | 1080p
    veo_resolution: str = "1080p"
    pexo_api_key: str = ""
    pexo_base_url: str = "https://api.pexo.ai"
    creatify_api_key: str = ""
    arcads_api_key: str = ""
    # Kling AI (default video provider). JWT auth (official): access + secret key.
    # Gateway (PiAPI/fal/...): set kling_api_key instead and leave access/secret blank.
    kling_access_key: str = ""
    kling_secret_key: str = ""
    kling_api_key: str = ""
    kling_base_url: str = "https://api-singapore.klingai.com"
    kling_model: str = "kling-v1"
    kling_duration: str = "10"  # seconds: "3".."15" (v3 up to 15)
    kling_mode: str = "std"     # "std"=720p | "pro"=1080p | "4k"
    # Pad/fit the product image to 9:16 (video_width x video_height) before
    # sending to image2video (whose output ratio follows the input image).
    kling_prepare_image: bool = True
    # HeyGen v3 (/v3/videos). Renders a finished, voiced video — no ElevenLabs/
    # merge needed. By DEFAULT HeyGen auto-picks an avatar + voice from its own
    # libraries (no IDs to look up). Pin them with heygen_avatar_id/voice_id, or
    # set heygen_image_url to animate a photo (image-to-video) instead.
    heygen_api_key: str = ""
    heygen_base_url: str = "https://api.heygen.com"
    heygen_avatar_id: str = ""           # blank => auto-select from /v2/avatars
    heygen_voice_id: str = ""            # blank => avatar default, else /v2/voices
    heygen_image_url: str = ""           # set => image-to-video (animate this photo)
    # Gender to cast is taken from profiles.json creative.narrator automatically;
    # this is only a fallback override. Empty narrator + empty here => the LLM
    # infers gender from the script.
    heygen_prefer_gender: str = ""
    # Avatar casting: True => LLM picks the best-fitting spokesperson per script
    # (tends to repeat the same person). False => pick RANDOMLY among the top-N
    # candidates so the presenter varies between videos. Voice always follows the
    # chosen avatar's default voice.
    heygen_smart_avatar: bool = False
    heygen_max_avatar_candidates: int = 50  # cap avatars shown to the LLM
    heygen_avatar_pool: int = 8             # randomize among this many top avatars
    # Avatar render engine. Blank => omit (HeyGen defaults to Avatar IV, which
    # standard avatars support). Set "avatar_v" ONLY for Avatar-V-eligible avatars.
    heygen_engine: str = ""
    heygen_resolution: str = "1080p"     # 4k | 1080p | 720p
    heygen_aspect_ratio: str = "9:16"    # auto | 16:9 | 9:16 | 4:5 | 5:4 | 1:1
    heygen_speed: float = 1.0            # voice speed (0.5–1.5)
    heygen_remove_background: bool = False
    # Avatar background:
    #   none   = HeyGen default backdrop
    #   script = generate a scene image from the script (needs an image provider)
    #   image  = use heygen_background as a fixed image URL
    #   color  = use heygen_background as a solid hex colour
    heygen_background_mode: str = "none"
    heygen_background: str = ""           # color hex or image URL (modes color/image)

    # ---- Image generation (used for HeyGen script-generated backgrounds) ----
    image_provider: str = "gemini"       # gemini (Imagen) | none
    imagen_model: str = "imagen-4.0-generate-001"
    # On HTTP 429 (quota/rate limit) wait and retry this many times. Imagen quota
    # is low by default — raise it on Google Cloud, or reduce image calls.
    imagen_max_retries_429: int = 1
    imagen_retry_wait_seconds: float = 20.0

    # ---- Product cutaway (post-step: briefly show the product full-screen) ----
    # Inserts a one-off full-screen product shot into the talking video while the
    # narration continues (the presenter leaves the screen for a few seconds).
    product_cutaway_enabled: bool = False
    product_cutaway_seconds: float = 2.5            # how long the product is shown
    product_cutaway_at: float = 0.4                 # fixed placement (fraction) if no mention
    product_cutaway_style: str = "zoom"             # zoom (gentle Ken-Burns) | still
    product_cutaway_sync_to_mention: bool = True    # place it when the script names the product

    # ---- Story mode (multi-scene b-roll: Gemini beats+scenes, ffmpeg edit) ----
    # Splits the script into beats, generates a cinematic scene per beat (Imagen)
    # and cuts between them under the HeyGen narration — a story, not a talking
    # head. Adds ~1 LLM + several Imagen calls per video.
    story_mode_enabled: bool = False
    story_beats: int = 4                 # number of narrative beats/scenes
    story_hook_on_avatar: bool = True    # keep the first beat on the presenter

    # ---- Hook card (bold text pattern-interrupt prepended before the avatar) ----
    hook_card_enabled: bool = False
    hook_card_seconds: float = 1.5      # how long the opening card shows
    hook_card_font_size: int = 96       # real px on the 1080x1920 frame
    hook_card_max_words: int = 10       # trim the hook line to this many words
    hook_card_uppercase: bool = True    # UPPERCASE the hook for impact

    # ---- Background music (Jamendo search -> random track -> ffmpeg mix) ----
    music_enabled: bool = False
    music_provider: str = "jamendo"
    jamendo_client_id: str = ""          # free from https://devportal.jamendo.com/
    jamendo_base_url: str = "https://api.jamendo.com/v3.0"
    music_query: str = "advertisement background"
    music_limit: int = 100               # candidates fetched, then random-picked
    music_volume: float = 0.18           # background level under the narration
    # Only pick tracks that allow commercial use + derivatives (by / by-sa / cc0).
    # The query "advertisement background" is mostly NonCommercial on Jamendo, so
    # leave this on and use a commercial-friendly query, or turn it off knowingly.
    music_commercial_only: bool = True

    # ---- Captions (post-step: burn subtitles from the script with ffmpeg) ----
    captions_enabled: bool = False
    caption_words_per_cue: int = 4      # words shown per on-screen caption line
    caption_font_size: int = 44         # subtitle font size in REAL pixels (1080x1920)
    caption_margin_v: int = 180         # distance from the bottom (px)

    # ---- Voiceover (TTS) + merge ----
    voice_enabled: bool = True
    voice_provider: str = "elevenlabs"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    ffmpeg_path: str = "ffmpeg"  # binary used to merge voiceover onto the video

    # ---- TikTok ad platform ----
    tiktok_access_token: str = ""
    tiktok_advertiser_id: str = ""
    tiktok_campaign_id: str = ""
    tiktok_adgroup_id: str = ""
    tiktok_base_url: str = "https://business-api.tiktok.com/open_api/v1.3"
    # Token auto-refresh (the access token expires). Leave app_id/secret/
    # refresh_token blank for a long-lived/static token (no refresh).
    tiktok_app_id: str = ""
    tiktok_app_secret: str = ""
    tiktok_refresh_token: str = ""
    tiktok_token_expires_at: float = 0.0  # unix epoch seconds; 0 => refresh on first use
    tiktok_token_store: str = "config/tiktok_token.json"

    # ---- Agent pipeline ----
    # Path to brand/audience/creative-rules profiles (JSON). QC thresholds and
    # brand voice are read from here (config/profiles.json).
    profiles_path: str = "config/profiles.json"
    # Pool of product image URLs (JSON). One is picked at random per video for the
    # product shot (the cutaway), so the product visual varies. Empty/missing =>
    # use the product's own image_url.
    product_images_path: str = "config/product_images.json"
    # How many script->video->QC attempts before a job is DISCARDED.
    job_max_attempts: int = 3

    # ---- Video output specs (TikTok/Reels) — enforced by Quality Review ----
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30
    video_formats: str = "mp4,mov"
    # 72 MB = strict Android limit (safe for both); iOS allows up to 287.
    video_max_file_mb: float = 72.0
    # Deep-verify actual resolution/fps via ffprobe (needs ffmpeg installed).
    # Off by default; gracefully skipped if ffprobe is unavailable.
    video_check_media: bool = False

    # ---- Script de-duplication (novelty) ----
    # lexical  = word 3-gram Jaccard (offline, zero-dep, default)
    # embedding = cosine over a LOCAL embedding model (semantic, no API)
    novelty_method: str = "lexical"
    # Similarity at/above which a script is "too similar" and is retried.
    # 0 => use the method default (lexical 0.5, embedding 0.85).
    novelty_threshold: float = 0.0
    # Local model for the embedding method (runs offline after first download).
    embedding_model: str = "all-MiniLM-L6-v2"

    # ---- Standalone cron scripts (scripts/cron_*.py) ----
    # Base URL of the running API the cron scripts call.
    api_base_url: str = "http://localhost:8000"
    # Video-generation cron: how often, and which products to generate for.
    generate_interval_hours: float = 24.0
    generate_product_ids: str = ""  # comma-separated product ids, e.g. "1,2,3"

    # ---- Campaign cloning (driven by scripts/cron_clone_campaign.py) ----
    # Cloning is never done in-app; the standalone cron script reads these.
    campaign_clone_interval_days: int = 30
    campaign_name_prefix: str = "Auto Campaign"

    # ---- Monitoring & pause rules ----
    monitor_interval_hours: int = 1
    pause_max_spend_no_conv: float = Field(default=50.0)
    pause_min_ctr: float = Field(default=0.005)
    pause_min_roas: float = Field(default=1.0)
    pause_min_spend_to_evaluate: float = Field(default=5.0)


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached ``Settings`` instance."""
    return Settings()
