"""Prepend a bold text HOOK CARD (pattern interrupt) before the avatar.

The first ~1.5s of a TikTok decides whether anyone watches. This builds a short,
bold full-screen text card from the script's hook line and concatenates it in
FRONT of the finished video, so viewers hit a punchy "stop the scroll" frame
before the talking presenter. The card STYLE (background + text colour) is rotated
randomly per video so they don't all look the same.

All ffmpeg: a lavfi colour background + the hook text burned via an ASS subtitle
(PlayRes = the real frame, so font sizes are real pixels), then a concat-filter
join with the main video. Graceful: any failure returns the original video.
"""
from __future__ import annotations

import logging
import os
import random
import re
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("service.hook_card")


@dataclass(slots=True)
class HookResult:
    path: str
    log: dict | None = None


# Rotated card styles: (background colour, text colour). Bold, high-contrast.
_STYLES = [
    ("&H00101010", "&H00FFFFFF"),   # near-black bg, white text
    ("&H00000000", "&H0000E0FF"),   # black bg, yellow text (BGR: FFE000)
    ("&H002F15C0", "&H00FFFFFF"),   # deep red bg, white text
    ("&H00FFFFFF", "&H00101010"),   # white bg, near-black text
]


def _ass_ts(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


class HookCardService:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        storage_dir: str = "generated_videos",
        enabled: bool = False,
        seconds: float = 1.5,
        font_size: int = 96,
        max_words: int = 10,
        uppercase: bool = True,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        timeout: int = 300,
        rng: random.Random | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._storage_dir = storage_dir
        self._enabled = enabled
        self._seconds = max(0.5, seconds)
        self._font_size = font_size
        self._max_words = max(2, max_words)
        self._uppercase = uppercase
        self._w = width
        self._h = height
        self._fps = fps
        self._timeout = timeout
        self._rng = rng or random.Random()

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    def apply(self, video_path: str, *, script_text: str) -> HookResult:
        if not self._enabled:
            return HookResult(video_path, None)

        def skip(reason: str, **extra) -> HookResult:
            return HookResult(video_path, self._entry({"seconds": self._seconds, **extra}, applied=False, reason=reason))

        if not self.available:
            logger.warning("ffmpeg not found; skipping hook card")
            return skip("ffmpeg_not_found")
        if not os.path.exists(video_path):
            return skip("no_video")

        hook = self._hook_text(script_text)
        if not hook:
            return skip("no_hook_text")

        bg, fg = self._rng.choice(_STYLES)
        work = os.path.dirname(os.path.abspath(video_path)) or "."
        stem = os.path.splitext(os.path.basename(video_path))[0]
        ass_name = f"{stem}_hook.ass"
        card_name = f"{stem}_hook_card.mp4"
        out_path = os.path.join(work, f"{stem}_hook.mp4")
        ass_path = os.path.join(work, ass_name)
        card_path = os.path.join(work, card_name)

        try:
            with open(ass_path, "w", encoding="utf-8") as fh:
                fh.write(self._build_ass(hook, fg))
        except OSError:
            return skip("ass_write_failed")

        details = {"seconds": self._seconds, "hook": hook, "bg": bg, "fg": fg}
        # 1) Build the card (colour bg + burned hook text + silent audio).
        card_cmd = [
            self._ffmpeg, "-y",
            "-f", "lavfi", "-i", f"color=c={self._ass_color_to_ffmpeg(bg)}:s={self._w}x{self._h}:r={self._fps}",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{self._seconds:.2f}",
            "-vf", f"subtitles={ass_name}",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            card_name,
        ]
        if not self._run(card_cmd, cwd=work):
            self._rm(ass_path)
            return HookResult(video_path, self._entry(details, applied=False, reason="card_build_failed"))
        self._rm(ass_path)

        # 2) Concat card + main video (normalise both streams so concat is safe).
        norm = (
            f"[0:v]fps={self._fps},scale={self._w}:{self._h},setsar=1[v0];"
            f"[1:v]fps={self._fps},scale={self._w}:{self._h},setsar=1[v1];"
            "[0:a]aresample=44100,aformat=sample_rates=44100:channel_layouts=stereo[a0];"
            "[1:a]aresample=44100,aformat=sample_rates=44100:channel_layouts=stereo[a1];"
            "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
        )
        concat_cmd = [
            self._ffmpeg, "-y",
            "-i", card_path, "-i", video_path,
            "-filter_complex", norm,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            out_path,
        ]
        ok = self._run(concat_cmd)
        self._rm(card_path)
        if not ok or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return HookResult(video_path, self._entry(details, applied=False, reason="concat_failed"))
        logger.info("Prepended hook card (%.1fs): %r", self._seconds, hook)
        return HookResult(out_path, self._entry(details, applied=True, output=os.path.basename(out_path)))

    # ---- internals ----
    def _hook_text(self, script_text: str) -> str:
        text = (script_text or "").strip()
        if not text:
            return ""
        first = re.split(r"(?<=[.!?])\s+", text)[0].strip(" .!?\"'")
        words = first.split()
        if len(words) > self._max_words:
            first = " ".join(words[: self._max_words])
        return first.upper() if self._uppercase else first

    def _build_ass(self, text: str, fg: str) -> str:
        # Centre-screen (Alignment 5), bold, big, outlined; PlayRes = real frame.
        text = text.replace("\n", " ")
        return (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {self._w}\nPlayResY: {self._h}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Hook,Arial,{self._font_size},{fg},&H000000FF,&H00000000,&H64000000,"
            "1,0,0,0,100,100,0,0,1,4,0,5,120,120,0,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,{_ass_ts(0)},{_ass_ts(self._seconds)},Hook,,0,0,0,,{text}\n"
        )

    @staticmethod
    def _ass_color_to_ffmpeg(ass: str) -> str:
        """Convert an ASS &H00BBGGRR colour to an ffmpeg 0xRRGGBB for lavfi color."""
        h = ass.replace("&H", "").replace("&", "")
        h = h[-6:] if len(h) >= 6 else h.rjust(6, "0")
        bb, gg, rr = h[0:2], h[2:4], h[4:6]
        return f"0x{rr}{gg}{bb}"

    def _run(self, cmd: list[str], cwd: str | None = None) -> bool:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout, cwd=cwd)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("hook card ffmpeg failed to run: %s", exc)
            return False
        if proc.returncode != 0:
            logger.warning("hook card ffmpeg rc=%s: %s", proc.returncode, proc.stderr[-400:])
            return False
        return True

    @staticmethod
    def _rm(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    @staticmethod
    def _entry(request: dict, *, applied: bool, reason: str | None = None, output: str | None = None) -> dict:
        response: dict = {"applied": applied}
        if output:
            response["output"] = output
        if reason:
            response["reason"] = reason
        return {
            "provider": "ffmpeg", "method": "HOOK_CARD", "endpoint": "(hook intro)",
            "request": request, "response": response, "status_code": None,
        }
