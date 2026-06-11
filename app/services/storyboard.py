"""Turn a single talking-head video into a multi-scene STORY video.

The HeyGen avatar provides continuous narration (audio + the presenter). This
service splits the script into narrative BEATS, has the LLM write a cinematic
b-roll image prompt per beat, generates each scene with the image provider
(Imagen), and composites them full-screen over the narration with ffmpeg so the
video cuts between scenes while the voice keeps playing — i.e. a story, not a
talking head. The first beat (the hook) stays on the avatar by default.

All Gemini (LLM + Imagen) + HeyGen (the narration) + ffmpeg (the edit). Timing is
approximate (beats placed by word count). Graceful: if ffmpeg or the image
provider is missing, the original video is returned unchanged.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger("service.storyboard")


@dataclass(slots=True)
class StoryResult:
    path: str
    logs: list[dict] = field(default_factory=list)


class StoryboardService:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        image_generator=None,
        llm=None,
        storage_dir: str = "generated_videos",
        enabled: bool = False,
        beats: int = 4,
        hook_on_avatar: bool = True,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        timeout: int = 900,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._img = image_generator
        self._llm = llm
        self._storage_dir = storage_dir
        self._enabled = enabled
        self._beats = max(2, beats)
        self._hook_on_avatar = hook_on_avatar
        self._w = width
        self._h = height
        self._fps = fps
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None and self._img is not None

    # ------------------------------------------------------------------ #
    def apply(self, video_path: str, *, script_text: str,
              duration_seconds: float | None = None) -> StoryResult:
        if not self._enabled:
            return StoryResult(video_path, [])

        def skip(reason: str) -> StoryResult:
            return StoryResult(video_path, [self._entry({"beats": self._beats}, applied=False, reason=reason)])

        if not self.available:
            logger.warning("Storyboard needs ffmpeg + an image generator; skipping")
            return skip("ffmpeg_or_image_provider_missing")
        if not (script_text or "").strip() or not os.path.exists(video_path):
            return skip("no_script_or_video")

        beats = self._split(script_text, self._beats)
        if len(beats) < 2:
            return skip("not_enough_beats")

        duration = duration_seconds or self._probe_duration(video_path) or max(
            8.0, len(script_text.split()) / 2.5
        )
        windows = self._windows(beats, duration)
        prompts = self._scene_prompts(beats)

        # Generate a scene image for every overlaid beat (hook may stay on avatar).
        overlays: list[tuple[str, float, float, str]] = []  # (img_path, start, end, prompt)
        beat_logs: list[dict] = []
        stem = os.path.splitext(os.path.basename(video_path))[0]
        for i, (chunk, (s, e), prompt) in enumerate(zip(beats, windows, prompts)):
            on_avatar = self._hook_on_avatar and i == 0
            if on_avatar:
                beat_logs.append({"beat": i + 1, "shot": "avatar", "window": [round(s, 2), round(e, 2)], "text": chunk})
                continue
            try:
                img = self._img.generate(prompt, width=self._w, height=self._h)
            except Exception as exc:
                logger.warning("Storyboard scene %d image gen failed (%s); beat stays on avatar", i + 1, exc)
                beat_logs.append({"beat": i + 1, "shot": "avatar(fallback)", "window": [round(s, 2), round(e, 2)],
                                  "error": str(exc)[:160]})
                continue
            img_path = os.path.join(self._storage_dir, f"{stem}_beat{i + 1}.jpg")
            try:
                with open(img_path, "wb") as fh:
                    fh.write(img)
            except OSError:
                continue
            overlays.append((img_path, s, e, prompt))
            beat_logs.append({
                "beat": i + 1, "shot": "b-roll", "window": [round(s, 2), round(e, 2)],
                "scene_prompt": prompt, "image": f"/videos/{os.path.basename(img_path)}",
            })

        if not overlays:
            return skip("no_scenes_generated")

        out_path = os.path.join(os.path.dirname(video_path), f"{stem}_story.mp4")
        cmd = self._build_cmd(video_path, overlays, out_path, duration)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Storyboard ffmpeg failed to run: %s", exc)
            return StoryResult(video_path, [self._entry({"beats": beat_logs}, applied=False, reason=f"ffmpeg_error: {exc}")])
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.warning("Storyboard failed (rc=%s): %s", proc.returncode, proc.stderr[-400:])
            return StoryResult(video_path, [self._entry({"beats": beat_logs}, applied=False, reason="ffmpeg_failed")])
        logger.info("Composed story video with %d b-roll scenes -> %s", len(overlays), out_path)
        log = self._entry({"beats": beat_logs}, applied=True, output=os.path.basename(out_path), scenes=len(overlays))
        return StoryResult(out_path, [log])

    # ---- beat splitting + timing ----
    @staticmethod
    def _split(script_text: str, beats: int) -> list[str]:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", script_text.strip()) if s.strip()]
        if not sentences:
            return []
        if len(sentences) <= beats:
            return sentences
        per = math.ceil(len(sentences) / beats)
        groups = [" ".join(sentences[i:i + per]) for i in range(0, len(sentences), per)]
        return groups[:beats]

    def _windows(self, beats: list[str], duration: float) -> list[tuple[float, float]]:
        counts = [max(1, len(b.split())) for b in beats]
        total = sum(counts)
        span = max(1.0, duration * 0.98)
        out, acc = [], 0
        for c in counts:
            start = span * acc / total
            acc += c
            end = span * acc / total
            out.append((start, end))
        return out

    def _scene_prompts(self, beats: list[str]) -> list[str]:
        fallback = [f"cinematic vertical 9:16 photo, emotional ad b-roll: {b}" for b in beats]
        if self._llm is None:
            return fallback
        system = (
            "You are an ad art director. For each BEAT of a short vertical (9:16) "
            "ad, write ONE vivid, cinematic, photographic text-to-image prompt for "
            "a b-roll shot that illustrates that beat's emotion and moment. Real and "
            "evocative; a person may appear naturally (hands, over-the-shoulder, "
            "silhouette); NO on-screen text. Return ONLY a JSON array of strings, "
            "one per beat, in order."
        )
        user = "BEATS:\n" + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(beats))
        try:
            raw = self._llm.complete(system, user) or ""
            arr = self._parse_array(raw)
            if arr and len(arr) >= len(beats):
                return [str(x) for x in arr[:len(beats)]]
        except Exception:
            logger.warning("Storyboard scene-prompt LLM call failed; using fallback", exc_info=True)
        return fallback

    @staticmethod
    def _parse_array(raw: str) -> list | None:
        raw = raw.strip()
        a, b = raw.find("["), raw.rfind("]")
        if a == -1 or b == -1 or b <= a:
            return None
        try:
            val = json.loads(raw[a:b + 1])
            return val if isinstance(val, list) else None
        except (ValueError, TypeError):
            return None

    # ---- ffmpeg: overlay each scene full-screen during its window ----
    def _build_cmd(self, video_path, overlays, out_path, duration) -> list[str]:
        total = int(duration * self._fps) + self._fps
        inputs = [self._ffmpeg, "-y", "-i", video_path]
        parts, prev = [], "0:v"
        for idx, (img_path, start, end, _prompt) in enumerate(overlays, start=1):
            inputs += ["-loop", "1", "-i", img_path]
            parts.append(
                f"[{idx}:v]scale={int(self._w * 1.15)}:{int(self._h * 1.15)},"
                f"zoompan=z='min(zoom+0.0008,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={total}:s={self._w}x{self._h}:fps={self._fps},setsar=1[p{idx}]"
            )
            label = f"v{idx}"
            parts.append(f"[{prev}][p{idx}]overlay=enable='between(t,{start:.2f},{end:.2f})'[{label}]")
            prev = label
        filt = ";".join(parts)
        return inputs + [
            "-filter_complex", filt,
            "-map", f"[{prev}]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-shortest",
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
    def _entry(request: dict, *, applied: bool, reason: str | None = None,
               output: str | None = None, scenes: int | None = None) -> dict:
        response: dict = {"applied": applied}
        if scenes is not None:
            response["scenes"] = scenes
        if output:
            response["output"] = output
        if reason:
            response["reason"] = reason
        return {
            "provider": "gemini+ffmpeg", "method": "STORYBOARD", "endpoint": "(multi-scene b-roll)",
            "request": request, "response": response, "status_code": None,
        }
