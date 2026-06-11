"""HeyGen implementation of the VideoGenerator interface.

HeyGen renders a finished, voiced, lip-synced video and does the TTS internally,
so no ElevenLabs voiceover or ffmpeg merge / Kling lip-sync is needed — hence
``produces_audio = True``: the pipeline treats HeyGen's output as final.

Endpoint by mode (both return {data:{video_id}} then a status with video_url):
  * avatar (default) -> POST /v2/video/generate  — works with the STANDARD
    avatars in /v2/avatars (mostly Avatar III). The newer /v3/videos avatar mode
    only accepts Avatar IV/V avatars, so standard ones are rejected there.
  * image (HEYGEN_IMAGE_URL set) -> POST /v3/videos  — animate a photo.

Casting is automatic and script-aware:
  * AVATAR per script — for each script the provider casts the best-fitting
    spokesperson from HeyGen's library (GET /v2/avatars). When an LLM is wired
    in, it picks by reading the script + visual_prompt; otherwise a gender/cost
    heuristic is used. The gender to cast for comes from the creative profile's
    narrator (directives.narrator, e.g. "male"), then HEYGEN_PREFER_GENDER, else
    none — in which case the LLM is free to infer gender from the script.
  * VOICE follows the avatar — the chosen avatar's ``default_voice_id`` is always
    used (HeyGen's tuned pairing), falling back to a gender-matched voice from
    GET /v2/voices only if the avatar has none.
The avatar/voice catalogs are fetched once and cached; the per-script choice is
memoised by script text (so submit retries don't re-pick or re-call the LLM).
Pin HEYGEN_AVATAR_ID / HEYGEN_VOICE_ID to override, or set HEYGEN_IMAGE_URL to
animate a photo (image-to-video) instead of an avatar.

API: https://developers.heygen.com/image-to-video  (auth header: x-api-key)
"""
from __future__ import annotations

import random

import requests

from app.core.entities import ProductInput, ScriptResult
from app.core.entities.profile import CreativeDirectives
from app.core.exceptions import VideoGenerationError
from app.core.http import translate_network_errors
from app.core.retry import with_retry
from app.providers.base_video import PollingVideoProvider


class HeyGenVideoProvider(PollingVideoProvider):
    name = "heygen"
    status_done = {"completed", "succeeded", "success", "done"}
    status_failed = {"failed", "error"}
    produces_audio = True  # voiceover + animation are baked in by HeyGen

    def __init__(
        self,
        *,
        api_key: str,
        avatar_id: str = "",        # pin an avatar; blank => cast per script
        voice_id: str = "",         # pin a voice; blank => follow the avatar
        image_url: str = "",        # set => image-to-video instead of avatar
        prefer_gender: str = "",    # narrow casting (e.g. "male"); "" = no bias
        llm=None,                   # optional LLMProvider for script-aware casting
        smart_avatar: bool = False, # True => LLM best-fit cast (tends to repeat);
                                    # False => random pick among the top-N (variety)
        max_avatar_candidates: int = 50,
        avatar_pool: int = 8,       # randomize among this many top candidates
        rng: random.Random | None = None,
        base_url: str = "https://api.heygen.com",
        engine: str = "",           # v3 avatar engine override (avatar IV/V only)
        avatar_style: str = "normal",
        width: int = 1080,
        height: int = 1920,
        resolution: str = "1080p",   # 4k | 1080p | 720p (image mode)
        aspect_ratio: str = "9:16",  # auto | 16:9 | 9:16 | 4:5 | 5:4 | 1:1 (image mode)
        speed: float = 1.0,          # voice speed 0.5–1.5
        remove_background: bool = False,
        image_generator=None,        # ImageGenerator, for background_mode="script"
        background_mode: str = "none",  # none | script | color | image
        background: str = "",        # color hex (color) or image url (image)
        timeout: int = 60,
        poll_interval: float = 10.0,
        max_poll_seconds: float = 900.0,
    ) -> None:
        self._avatar_id = avatar_id
        self._voice_id = voice_id
        self._image_url = image_url
        self._prefer_gender = (prefer_gender or "").lower()
        self._llm = llm
        self._smart_avatar = smart_avatar
        self._max_candidates = max(1, max_avatar_candidates)
        self._pool = max(1, avatar_pool)
        self._rng = rng or random.Random()
        self._engine = engine
        self._avatar_style = avatar_style
        self._width = width
        self._height = height
        self._resolution = resolution
        self._aspect_ratio = aspect_ratio
        self._speed = speed
        self._remove_background = remove_background
        self._image_gen = image_generator
        self._background_mode = (background_mode or "none").lower()
        self._background_value = background
        self._avatars_cache: list[dict] | None = None
        self._voices_cache: list[dict] | None = None
        self._choice_cache: dict[str, tuple[str | None, str | None]] = {}
        self._bg_cache: dict[str, dict | None] = {}

        # Endpoint depends on the mode:
        #  * image  -> v3 image-to-video (animate a photo); needs a face.
        #  * avatar -> v2 avatar generation, which works with the STANDARD
        #    avatars from /v2/avatars (mostly Avatar III). /v3/videos avatar mode
        #    only accepts Avatar IV/V avatars, so standard ones 400 there.
        if image_url:
            self._mode = "image"
            self.create_path = "/v3/videos"
            self.status_path = "/v3/videos/{job_id}"
        else:
            self._mode = "avatar"
            self.create_path = "/v2/video/generate"
            self.status_path = "/v1/video_status.get?video_id={job_id}"

        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            poll_interval=poll_interval,
            max_poll_seconds=max_poll_seconds,
        )

    # ---- auth: HeyGen uses an x-api-key header, not a bearer token ----
    def auth_headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    # ------------------------------------------------------------------ #
    # Catalogs (fetched once, cached).
    # ------------------------------------------------------------------ #
    def _catalog_avatars(self) -> list[dict]:
        if self._avatars_cache is None:
            self._avatars_cache = self._list("/v2/avatars").get("avatars") or []
        return self._avatars_cache

    def _catalog_voices(self) -> list[dict]:
        if self._voices_cache is None:
            self._voices_cache = self._list("/v2/voices").get("voices") or []
        return self._voices_cache

    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _list(self, path: str) -> dict:
        resp = requests.get(
            f"{self._base_url}{path}", headers=self.auth_headers(), timeout=self._timeout
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(
                f"{path} HTTP {resp.status_code}: {resp.text[:200]}", provider=self.name
            )
        data = resp.json().get("data", {}) or {}
        # Record a compact entry (counts, not the whole catalog) for the audit trail.
        counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        self.record_call(method="GET", endpoint=path, status_code=resp.status_code, response=counts)
        return data

    # ------------------------------------------------------------------ #
    # Per-script casting: avatar (by script) + voice (by avatar).
    # ------------------------------------------------------------------ #
    def _effective_gender(self, directives: CreativeDirectives | None) -> str:
        """Gender to cast for. Prefer the creative profile's narrator (the source
        of truth for who is speaking), then the static config, else none (let the
        LLM decide gender from the script)."""
        narrator = (directives.narrator if directives else "") or ""
        return (narrator or self._prefer_gender or "").lower()

    def _resolve(
        self, script: ScriptResult, directives: CreativeDirectives | None = None
    ) -> tuple[str | None, str | None]:
        """Return (avatar_id, voice_id) for this script (memoised)."""
        gender = self._effective_gender(directives)
        key = f"{gender}\n{script.text or ''}"
        cached = self._choice_cache.get(key)
        if cached is not None:
            return cached

        avatar_id: str | None = self._avatar_id or None
        voice_id: str | None = self._voice_id or None
        avatar: dict | None = None

        if not self._image_url:
            if avatar_id and voice_id:
                pass  # fully pinned: no catalog lookup needed
            elif avatar_id:
                avatar = self._find_avatar(avatar_id)  # need it for the voice
            else:
                avatar = self._select_avatar(script, gender)
                avatar_id = avatar.get("avatar_id") if avatar else None

        # Voice ALWAYS follows the avatar unless explicitly pinned.
        if not voice_id:
            voice_id = self._voice_for_avatar(avatar, gender)

        choice = (avatar_id, voice_id)
        self._choice_cache[key] = choice
        self.record_call(
            method="SELECT",
            endpoint="(casting)",
            request={"gender": gender, "smart_avatar": self._smart_avatar, "mode": self._mode},
            response={
                "avatar_id": avatar_id,
                "voice_id": voice_id,
                "avatar_name": avatar.get("avatar_name") if avatar else None,
            },
        )
        return choice

    def _find_avatar(self, avatar_id: str) -> dict | None:
        return next(
            (a for a in self._catalog_avatars() if a.get("avatar_id") == avatar_id), None
        )

    def _candidate_avatars(self, gender: str) -> list[dict]:
        avatars = self._catalog_avatars()
        if gender:
            matched = [a for a in avatars if str(a.get("gender", "")).lower() == gender]
            avatars = matched or avatars
        # Non-premium first (cheaper), then stable id order; cap the list size.
        avatars = sorted(
            avatars, key=lambda a: (0 if not a.get("premium") else 1, str(a.get("avatar_id", "")))
        )
        return avatars[: self._max_candidates]

    def _select_avatar(self, script: ScriptResult, gender: str) -> dict:
        candidates = self._candidate_avatars(gender)
        if not candidates:
            raise VideoGenerationError("HeyGen returned no avatars to choose from", provider=self.name)
        if self._smart_avatar and self._llm is not None and len(candidates) > 1:
            picked = self._llm_pick_avatar(script, candidates)
            chosen = next((a for a in candidates if a.get("avatar_id") == picked), None)
            if chosen:
                self._log.info(
                    "HeyGen cast avatar %s (%s) for script via LLM",
                    chosen.get("avatar_id"), chosen.get("avatar_name"),
                )
                return chosen
        # Default: pick RANDOMLY among the top-N candidates so the presenter
        # varies between videos (instead of always the first/best-fit one).
        pool = candidates[: self._pool]
        chosen = self._rng.choice(pool)
        self._log.info(
            "HeyGen cast avatar %s (%s) randomly from a pool of %d",
            chosen.get("avatar_id"), chosen.get("avatar_name"), len(pool),
        )
        return chosen

    def _llm_pick_avatar(self, script: ScriptResult, candidates: list[dict]) -> str | None:
        listing = "\n".join(
            f"{a.get('avatar_id')} | {a.get('avatar_name', '')} | {a.get('gender', '')}"
            for a in candidates
        )
        system = (
            "You are casting the on-camera spokesperson for a short vertical ad. "
            "Choose the ONE avatar whose persona — gender, apparent age and look "
            "implied by the name — best fits the script's speaker. "
            "Reply with ONLY the avatar_id, nothing else."
        )
        user = (
            f"SCRIPT (spoken by the avatar):\n{script.text}\n\n"
            f"SPEAKER NOTES: {script.visual_prompt or '(none)'}\n\n"
            f"AVATARS (avatar_id | name | gender):\n{listing}\n\n"
            "Return only the best avatar_id."
        )
        try:
            raw = (self._llm.complete(system, user) or "").strip()
        except Exception:  # never let casting break video generation
            self._log.warning("HeyGen LLM avatar casting failed; using heuristic", exc_info=True)
            return None
        ids = {a.get("avatar_id") for a in candidates}
        # Exact first token, else any id that appears in the reply.
        first = raw.split()[0].strip("\"'`,.") if raw.split() else ""
        if first in ids:
            return first
        return next((a_id for a_id in ids if a_id and a_id in raw), None)

    def _voice_for_avatar(self, avatar: dict | None, gender: str = "") -> str | None:
        if avatar and avatar.get("default_voice_id"):
            return avatar["default_voice_id"]
        voices = self._catalog_voices()
        if not voices:
            return None
        # Match the avatar's own gender if known, else the requested gender.
        gender = str(avatar.get("gender", "")).lower() if avatar else gender
        chosen = self._choose_voice(voices, gender)
        self._log.info(
            "HeyGen voice %s (%s) selected to match the avatar",
            chosen.get("voice_id"), chosen.get("name"),
        )
        return chosen.get("voice_id")

    # ---- pure ranking helpers (unit-tested) ----
    @staticmethod
    def _choose_avatar(avatars: list[dict], prefer_gender: str) -> dict:
        if not avatars:
            raise VideoGenerationError("HeyGen returned no avatars to choose from", provider="heygen")
        return sorted(
            avatars,
            key=lambda a: (
                0 if prefer_gender and str(a.get("gender", "")).lower() == prefer_gender else 1,
                0 if not a.get("premium") else 1,
                str(a.get("avatar_id", "")),
            ),
        )[0]

    @staticmethod
    def _choose_voice(voices: list[dict], prefer_gender: str) -> dict:
        if not voices:
            raise VideoGenerationError("HeyGen returned no voices to choose from", provider="heygen")

        def is_english(v: dict) -> bool:
            return str(v.get("language", "")).lower().startswith(("en", "english"))

        return sorted(
            voices,
            key=lambda v: (
                0 if prefer_gender and str(v.get("gender", "")).lower() == prefer_gender else 1,
                0 if is_english(v) else 1,
                str(v.get("voice_id", "")),
            ),
        )[0]

    # ---- preview (dry run): build the payload WITHOUT submitting or media gen ----
    def preview(self, product, script, directives=None) -> dict:
        self._calls = []
        self.record_call(method="SCRIPT", endpoint="(script)", request=self._script_snapshot(script))
        avatar_id, voice_id = self._resolve(script, directives)  # read-only selection
        if self._mode == "image":
            payload = self._image_payload(product, script, voice_id)
        else:
            payload = self._avatar_payload(product, script, avatar_id, voice_id, preview=True)
        self.record_call(method="PREVIEW (not sent)", endpoint=self.create_path, request=payload)
        return {"payload": payload, "calls": list(self._calls)}

    # ---- payload / parsing ----
    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        if not (script.text or "").strip():
            raise VideoGenerationError(
                "script text is empty — cannot generate a talking video", provider=self.name
            )
        avatar_id, voice_id = self._resolve(script, directives)
        if self._mode == "image":
            return self._image_payload(product, script, voice_id)
        return self._avatar_payload(product, script, avatar_id, voice_id)

    def _avatar_payload(self, product, script, avatar_id, voice_id, *, preview: bool = False) -> dict:
        """v2 /v2/video/generate — works with the standard /v2/avatars."""
        voice: dict = {"type": "text", "input_text": script.text, "voice_id": voice_id}
        if self._speed != 1.0:
            voice["speed"] = self._speed
        video_input: dict = {
            "character": {
                "type": "avatar",
                "avatar_id": avatar_id,
                "avatar_style": self._avatar_style,
            },
            "voice": voice,
        }
        background = self._background(script, preview=preview)
        if background:
            video_input["background"] = background
        return {
            "video_inputs": [video_input],
            "dimension": {"width": self._width, "height": self._height},
            "title": (product.name or "ad")[:100],
        }

    # ------------------------------------------------------------------ #
    # Background: a scene generated from the script (or a fixed image/color).
    # ------------------------------------------------------------------ #
    def _background(self, script: ScriptResult, *, preview: bool = False) -> dict | None:
        mode = self._background_mode
        if mode == "none":
            return None
        if mode == "color":
            return {"type": "color", "value": self._background_value or "#000000"}
        if mode == "image":
            return {"type": "image", "url": self._background_value} if self._background_value else None
        if mode != "script":
            return None
        # mode == "script": derive the scene prompt; in preview we stop there
        # (no image generation / upload), otherwise generate + upload (cached).
        if preview:
            prompt = self._scene_prompt(script)
            self.record_call(
                method="IMAGE (preview)", endpoint="(background)",
                request={"prompt": prompt}, response={"note": "image not generated in preview"},
            )
            return {"type": "image", "url": "<scene image generated at run time>",
                    "scene_prompt": prompt}
        key = script.text or ""
        if key in self._bg_cache:
            return self._bg_cache[key]
        bg: dict | None = None
        if self._image_gen is None:
            self._log.warning("HEYGEN_BACKGROUND_MODE=script but no image generator is configured")
        else:
            try:
                prompt = self._scene_prompt(script)
                img = self._image_gen.generate(prompt, width=self._width, height=self._height)
                url = self._upload_asset(img)
                bg = {"type": "image", "url": url}
                self.record_call(
                    method="IMAGE", endpoint="(background)",
                    request={"prompt": prompt, "provider": getattr(self._image_gen, "name", "image"),
                             "size": f"{self._width}x{self._height}"},
                    response={"url": url, "image_bytes": len(img)},
                )
            except Exception as exc:  # background must never break video generation
                self._log.warning("Background generation failed (%s); using HeyGen default", exc)
                bg = None
        self._bg_cache[key] = bg
        return bg

    def _scene_prompt(self, script: ScriptResult) -> str:
        """Build a text-to-image prompt for an EMPTY background scene (no people —
        the avatar is the person) derived from the script."""
        fallback = (
            f"{script.visual_prompt or script.text}, empty scene, no people, "
            "photographic background, soft depth of field, vertical 9:16"
        )
        if self._llm is None:
            return fallback[:300]
        system = (
            "You write a single concise text-to-image prompt for a 9:16 vertical "
            "BACKGROUND scene for an ad. Describe ONLY the setting/environment "
            "implied by the script — NO people, no text, empty scene, photographic, "
            "well lit, natural depth of field. One sentence, under 200 characters."
        )
        user = (
            f"SCRIPT:\n{script.text}\n\nSCENE NOTE: {script.visual_prompt or '(none)'}\n\n"
            "Background image prompt:"
        )
        try:
            out = (self._llm.complete(system, user) or "").strip()
            return (out or fallback)[:300]
        except Exception:
            return fallback[:300]

    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _upload_asset(self, image_bytes: bytes) -> str:
        """Upload an image to HeyGen (POST /v3/assets) and return its public URL."""
        resp = requests.post(
            f"{self._base_url}/v3/assets",
            headers={"x-api-key": self._api_key},  # no JSON content-type for multipart
            files={"file": ("background.jpg", image_bytes, "image/jpeg")},
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(
                f"/v3/assets HTTP {resp.status_code}: {resp.text[:200]}", provider=self.name
            )
        data = resp.json().get("data", {}) or {}
        url = data.get("url")
        if not url:
            raise VideoGenerationError("HeyGen asset upload returned no url", provider=self.name)
        return url

    def _image_payload(self, product, script, voice_id) -> dict:
        """v3 /v3/videos image-to-video — animate a photo (needs a face)."""
        payload: dict = {
            "type": "image",
            "image": {"type": "url", "url": self._image_url},
            "script": script.text,
            "voice_id": voice_id,
            "aspect_ratio": self._aspect_ratio,
            "resolution": self._resolution,
            "title": (product.name or "ad")[:100],
        }
        if self._engine:
            payload["engine"] = {"type": self._engine}
        if self._speed != 1.0:
            payload["voice_settings"] = {"speed": self._speed}
        if self._remove_background:
            payload["remove_background"] = True
        return payload

    def parse_job_id(self, data: dict) -> str | None:
        err = data.get("error")
        if err:
            raise VideoGenerationError(f"HeyGen error: {err}", provider=self.name)
        body = data.get("data") or {}
        return body.get("video_id") or body.get("id")

    def parse_status(self, data: dict) -> tuple[str, str | None, float | None]:
        body = data.get("data", data)
        status = str(body.get("status", "")).lower()
        url = body.get("video_url") or body.get("video_url_caption")
        if status in self.status_failed and body.get("failure_message"):
            self._log.error("HeyGen job failed: %s", body.get("failure_message"))
        duration = body.get("duration")
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        return status, url, duration
