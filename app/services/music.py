"""Mix background music under the narration with ffmpeg.

Fetches a random track from the music provider (Jamendo), downloads it, and mixes
it UNDER the existing narration: the music is lowered, looped to cover the whole
video, faded in/out, and limited to avoid clipping. The video stream is copied
(no re-encode), only the audio is re-mixed.

Graceful: if music is disabled, ffmpeg/provider is missing, or no track is found,
the original video is returned unchanged.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("service.music")


@dataclass(slots=True)
class MusicResult:
    path: str
    log: dict | None = None


class MusicService:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        provider=None,
        storage_dir: str = "generated_videos",
        enabled: bool = False,
        volume: float = 0.18,
        fade: float = 2.0,
        timeout: int = 300,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._provider = provider
        self._storage_dir = storage_dir
        self._enabled = enabled
        self._volume = max(0.0, volume)
        self._fade = max(0.0, fade)
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None and self._provider is not None

    def apply(self, video_path: str, *, duration_seconds: float | None = None) -> MusicResult:
        if not self._enabled:
            return MusicResult(video_path, None)

        def skip(reason: str, **extra) -> MusicResult:
            return MusicResult(video_path, self._entry({"volume": self._volume, **extra}, applied=False, reason=reason))

        if not self.available:
            logger.warning("Music needs ffmpeg + a music provider; skipping")
            return skip("ffmpeg_or_provider_missing")
        if not os.path.exists(video_path):
            return skip("no_video")

        track = self._provider.pick()
        if not track or not track.download_url:
            return skip("no_track_found")

        stem = os.path.splitext(os.path.basename(video_path))[0]
        mp3_path = os.path.join(self._storage_dir, f"{stem}_music.mp3")
        if not self._provider.download(track.download_url, mp3_path):
            return skip("download_failed", track=track.name)

        duration = duration_seconds or self._probe_duration(video_path) or 30.0
        out_path = os.path.join(os.path.dirname(video_path), f"{stem}_music.mp4")
        cmd = self._build_cmd(video_path, mp3_path, out_path, duration)
        details = {
            "volume": self._volume, "track": track.name, "artist": track.artist,
            "license": track.license, "url": track.download_url,
        }
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("ffmpeg music mix failed to run: %s", exc)
            self._rm(mp3_path)
            return MusicResult(video_path, self._entry(details, applied=False, reason=f"ffmpeg_error: {exc}"))
        self._rm(mp3_path)
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.warning("Music mix failed (rc=%s): %s", proc.returncode, proc.stderr[-400:])
            return MusicResult(video_path, self._entry(details, applied=False, reason="ffmpeg_failed"))
        logger.info("Mixed music '%s' by %s -> %s", track.name, track.artist, out_path)
        return MusicResult(out_path, self._entry(details, applied=True, output=os.path.basename(out_path)))

    # ---- internals ----
    def _build_cmd(self, video_path, mp3_path, out_path, duration) -> list[str]:
        fade_out_start = max(0.0, duration - self._fade)
        # Lower + fade the music, loop it to cover the video, mix under the voice
        # (normalize=0 keeps the narration at full volume), then limit to avoid clipping.
        filt = (
            f"[1:a]volume={self._volume},afade=t=in:st=0:d=1,"
            f"afade=t=out:st={fade_out_start:.2f}:d={self._fade}[bg];"
            f"[0:a][bg]amix=inputs=2:duration=first:normalize=0:dropout_transition=0,"
            f"alimiter=limit=0.95[a]"
        )
        return [
            self._ffmpeg, "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-i", mp3_path,
            "-filter_complex", filt,
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            out_path,
        ]

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
            "provider": "jamendo+ffmpeg", "method": "MUSIC", "endpoint": "(background music)",
            "request": request, "response": response, "status_code": None,
        }
