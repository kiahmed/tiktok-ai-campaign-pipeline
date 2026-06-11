"""Insert a one-off product 'cutaway' into a finished talking video.

The avatar/presenter video keeps its continuous audio (the narration), but for a
short window the video cuts to a full-screen shot of the product (the person
leaves the screen) — then back to the presenter. It is a post-processing step:
the video provider (HeyGen) only renders the avatar; this overlays the product
afterwards with ffmpeg.

Timing: if the script mentions the product, the cutaway is placed at the
estimated moment of that mention (word position x duration); otherwise at a fixed
fraction of the way through. Style is a static still or a gentle Ken-Burns zoom.
The product image is padded to 9:16 (blurred fill) via image_prep, reused here.

Graceful: if ffmpeg is missing, the image can't be prepared, or the clip is too
short, the original video is returned unchanged.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("service.product_cutaway")


@dataclass(slots=True)
class CutawayResult:
    path: str                 # the (possibly new) video path
    log: dict | None = None   # a CUTAWAY entry for the video's API-call log


class ProductCutawayService:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        enabled: bool = False,
        seconds: float = 2.5,
        at_fraction: float = 0.4,
        style: str = "zoom",          # zoom | still
        sync_to_mention: bool = True,
        image_pool=None,              # optional ProductImagePool (random product photo)
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        timeout: int = 300,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._enabled = enabled
        self._pool = image_pool
        self._seconds = max(0.5, seconds)
        self._at = min(0.9, max(0.0, at_fraction))
        self._style = (style or "zoom").lower()
        self._sync = sync_to_mention
        self._w = width
        self._h = height
        self._fps = fps
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    # ------------------------------------------------------------------ #
    def apply(self, video_path: str, *, product, script_text: str,
              duration_seconds: float | None = None) -> CutawayResult:
        """Return a CutawayResult with the (possibly new) video path and a
        CUTAWAY log entry. The original path is kept unchanged on skip/failure."""
        if not self._enabled:
            return CutawayResult(video_path, None)  # disabled -> no log noise

        req = {"style": self._style, "seconds": self._seconds, "sync_to_mention": self._sync}
        # Pick a random product photo from the pool (falls back to the product's own).
        own = getattr(product, "image_url", "")
        image_url = self._pool.random_url(own) if self._pool is not None else own

        def skip(reason: str, **extra) -> CutawayResult:
            return CutawayResult(video_path, self._entry({**req, **extra}, applied=False, reason=reason))

        if not self.available:
            logger.warning("ffmpeg not found (%s); skipping product cutaway", self._ffmpeg)
            return skip("ffmpeg_not_found")
        if not image_url or not os.path.exists(video_path):
            return skip("no_product_image_or_video")

        duration = self._duration(video_path, duration_seconds, script_text)
        if duration < self._seconds + 1.5:
            logger.info("Video too short (%.1fs) for a %.1fs cutaway; skipping", duration, self._seconds)
            return skip("video_too_short", duration=round(duration, 2))

        t1 = self._cut_start(script_text, getattr(product, "name", ""), duration)
        t2 = t1 + self._seconds

        img_path = self._prep_product_image(image_url, video_path)
        if not img_path:
            return skip("image_prep_failed", duration=round(duration, 2))

        stem, ext = os.path.splitext(video_path)
        out_path = f"{stem}_promo{ext or '.mp4'}"
        cmd = self._build_cmd(video_path, img_path, out_path, t1, t2, duration)
        details = {**req, "duration": round(duration, 2), "t1": round(t1, 2),
                   "t2": round(t2, 2), "product_image": image_url}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ffmpeg product cutaway failed to run: %s", exc)
            self._cleanup(img_path, None)
            return CutawayResult(video_path, self._entry(details, applied=False, reason=f"ffmpeg_error: {exc}"))
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.warning("Product cutaway failed (rc=%s): %s", proc.returncode, proc.stderr[-400:])
            self._cleanup(img_path, None)
            return CutawayResult(video_path, self._entry(details, applied=False, reason="ffmpeg_failed"))
        self._cleanup(img_path, None)
        logger.info("Inserted product cutaway %.1fs–%.1fs -> %s", t1, t2, out_path)
        return CutawayResult(out_path, self._entry(details, applied=True, output=os.path.basename(out_path)))

    @staticmethod
    def _entry(request: dict, *, applied: bool, reason: str | None = None, output: str | None = None) -> dict:
        response: dict = {"applied": applied}
        if output:
            response["output"] = output
        if reason:
            response["reason"] = reason
        return {
            "provider": "ffmpeg", "method": "CUTAWAY", "endpoint": "(product cutaway)",
            "request": request, "response": response, "status_code": None,
        }

    # ---- internals ----
    def _build_cmd(self, video_path, img_path, out_path, t1, t2, duration) -> list[str]:
        enable = f"between(t,{t1:.2f},{t2:.2f})"
        if self._style == "still":
            prep = f"[1:v]scale={self._w}:{self._h},setsar=1[p]"
        else:  # gentle Ken-Burns zoom over the whole clip; visible during the window
            total = int(duration * self._fps) + self._fps
            prep = (
                f"[1:v]scale={int(self._w * 1.15)}:{int(self._h * 1.15)},"
                f"zoompan=z='min(zoom+0.0010,1.12)'"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={total}:s={self._w}x{self._h}:fps={self._fps},setsar=1[p]"
            )
        filt = f"{prep};[0:v][p]overlay=enable='{enable}':x=0:y=0[v]"
        return [
            self._ffmpeg, "-y",
            "-i", video_path,
            "-loop", "1", "-i", img_path,
            "-filter_complex", filt,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-shortest",
            out_path,
        ]

    def _cut_start(self, script_text: str, product_name: str, duration: float) -> float:
        frac = self._at
        if self._sync:
            m = self._mention_fraction(script_text, product_name)
            if m is not None:
                frac = m
        t1 = frac * duration
        # keep the whole window inside the clip with a little margin
        return max(0.5, min(t1, duration - self._seconds - 0.5))

    @staticmethod
    def _mention_fraction(script_text: str, product_name: str) -> float | None:
        words = (script_text or "").split()
        if not words or not product_name:
            return None
        tokens = [w.strip(".,!?'\"").lower() for w in product_name.split() if len(w) >= 4]
        if not tokens:
            return None
        for i, w in enumerate(words):
            wl = w.strip(".,!?'\"").lower()
            if any(tok in wl or wl in tok for tok in tokens):
                return i / len(words)
        return None

    def _duration(self, video_path: str, passed: float | None, script_text: str) -> float:
        probed = self._probe_duration(video_path)
        if probed:
            return probed
        if passed:
            return passed
        return max(8.0, len((script_text or "").split()) / 2.5)

    def _probe_duration(self, video_path: str) -> float | None:
        probe = "ffprobe"
        # ffprobe usually sits next to ffmpeg; fall back to PATH lookup.
        if os.path.sep in self._ffmpeg:
            cand = os.path.join(os.path.dirname(self._ffmpeg), "ffprobe")
            probe = cand if shutil.which(cand) else "ffprobe"
        if not shutil.which(probe):
            return None
        try:
            out = subprocess.run(
                [probe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=30,
            )
            return float(out.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def _prep_product_image(self, image_url: str, video_path: str) -> str | None:
        from app.services.image_prep import url_to_vertical_b64

        b64 = url_to_vertical_b64(image_url, width=self._w, height=self._h)
        if not b64:
            logger.warning("Could not prepare product image for cutaway: %s", image_url)
            return None
        path = os.path.splitext(video_path)[0] + "_promo_src.jpg"
        try:
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(b64))
            return path
        except OSError:
            logger.warning("Could not write prepared product image", exc_info=True)
            return None

    @staticmethod
    def _cleanup(tmp_img: str | None, ret: str | None) -> str | None:
        if tmp_img and os.path.exists(tmp_img):
            try:
                os.remove(tmp_img)
            except OSError:
                pass
        return ret
