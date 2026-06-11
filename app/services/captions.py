"""Burn captions (subtitles) into a finished video with ffmpeg.

HeyGen's /v2/video/generate (standard avatars) doesn't expose a caption flag, so
captions are added here as a post-step that works for ANY provider: split the
script into short cues, time them proportionally across the video's duration,
write an SRT and burn it in with the ffmpeg ``subtitles`` filter.

Timing is approximate (no word-level timestamps) — cues are distributed by word
count across the speech, which reads well for short vertical ads. Graceful: if
ffmpeg is missing or the script is empty, the original video is returned.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("service.captions")


@dataclass(slots=True)
class CaptionResult:
    path: str
    log: dict | None = None


def _ass_ts(seconds: float) -> str:
    """Format seconds as an ASS timestamp H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


class CaptionService:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        enabled: bool = False,
        words_per_cue: int = 4,
        font_size: int = 44,
        margin_v: int = 180,
        width: int = 1080,
        height: int = 1920,
        timeout: int = 300,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._enabled = enabled
        self._wpc = max(1, words_per_cue)
        self._font_size = font_size
        self._margin_v = margin_v
        self._w = width
        self._h = height
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    def apply(self, video_path: str, *, script_text: str,
              duration_seconds: float | None = None) -> CaptionResult:
        if not self._enabled:
            return CaptionResult(video_path, None)

        req = {"words_per_cue": self._wpc, "font_size": self._font_size}

        def skip(reason: str) -> CaptionResult:
            return CaptionResult(video_path, self._entry({**req}, applied=False, reason=reason))

        if not self.available:
            logger.warning("ffmpeg not found (%s); skipping captions", self._ffmpeg)
            return skip("ffmpeg_not_found")
        if not (script_text or "").strip() or not os.path.exists(video_path):
            return skip("no_script_or_video")

        duration = duration_seconds or self._probe_duration(video_path) or max(
            6.0, len(script_text.split()) / 2.5
        )
        ass = self._build_ass(script_text, duration)
        if not ass:
            return skip("no_cues")

        work_dir = os.path.dirname(os.path.abspath(video_path)) or "."
        vid_name = os.path.basename(video_path)
        stem, ext = os.path.splitext(vid_name)
        ass_name = f"{stem}_cc.ass"
        out_name = f"{stem}_cc{ext or '.mp4'}"
        ass_path = os.path.join(work_dir, ass_name)
        out_path = os.path.join(work_dir, out_name)
        try:
            with open(ass_path, "w", encoding="utf-8") as fh:
                fh.write(ass)
        except OSError:
            return skip("ass_write_failed")

        # Run with cwd=work_dir so the subtitles filter gets a bare filename
        # (avoids Windows drive-letter ':' escaping issues in the filter graph).
        # The ASS carries PlayResX/Y = the real frame, so the font size is in
        # actual pixels (no 6x upscaling like a bare SRT).
        cmd = [
            self._ffmpeg, "-y", "-i", vid_name,
            "-vf", f"subtitles={ass_name}",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "copy", out_name,
        ]
        details = {**req, "duration": round(duration, 2), "cues": ass.count("Dialogue:")}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout, cwd=work_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ffmpeg caption burn failed to run: %s", exc)
            self._rm(ass_path)
            return CaptionResult(video_path, self._entry(details, applied=False, reason=f"ffmpeg_error: {exc}"))
        self._rm(ass_path)
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.warning("Caption burn failed (rc=%s): %s", proc.returncode, proc.stderr[-400:])
            return CaptionResult(video_path, self._entry(details, applied=False, reason="ffmpeg_failed"))
        logger.info("Burned %d caption cues -> %s", details["cues"], out_path)
        return CaptionResult(out_path, self._entry(details, applied=True, output=out_name))

    # ---- internals ----
    def _build_ass(self, script_text: str, duration: float) -> str | None:
        words = script_text.split()
        if not words:
            return None
        cues = [words[i:i + self._wpc] for i in range(0, len(words), self._wpc)]
        total = len(words)
        span = max(1.0, duration * 0.98)
        # ASS style: white text, black outline, BOLD, bottom-centre (Alignment 2),
        # font size + bottom margin in REAL pixels because PlayResX/Y = the frame.
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self._w}\n"
            f"PlayResY: {self._h}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,Arial,{self._font_size},&H00FFFFFF,&H000000FF,"
            f"&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,1,2,80,80,{self._margin_v},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        t = 0.0
        lines = []
        for cue in cues:
            cue_dur = span * (len(cue) / total)
            start, end = t, min(span, t + cue_dur)
            t = end
            text = " ".join(cue).replace("\n", " ")
            lines.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{text}")
        return header + "\n".join(lines) + "\n"

    def _probe_duration(self, video_path: str) -> float | None:
        probe = "ffprobe"
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
            "provider": "ffmpeg", "method": "CAPTIONS", "endpoint": "(burn subtitles)",
            "request": request, "response": response, "status_code": None,
        }
