"""③ Quality Review Agent — APPROVE or REJECT a video candidate.

Phase 1 is deterministic & rule-based (no LLM), enforcing the creative rules
from the brand profile. It can genuinely reject, and every verdict — pass or
fail — is written to ``qc_reviews`` with structured ``failure_codes`` so the
Creative Strategist can learn from it (the "Save Reason -> Knowledge" arrow).

Phase 3 adds an LLM judge on top (brand-voice fit, script/video coherence)
behind the same contract.
"""
from __future__ import annotations

import logging
import os

from app.agents.base import Agent, AgentResult
from app.core.exceptions import NotFoundError
from app.database.models import CreativeJob, JobStatus, QcVerdict
from app.repositories import QcReviewRepository, ScriptRepository, VideoRepository
from app.services.profile_service import ProfileService
from app.services.qc_judge import QcJudge

logger = logging.getLogger("agent.qc")


class QualityReviewAgent(Agent):
    name = "quality_review"

    def __init__(
        self,
        *,
        profile_service: ProfileService,
        script_repo: ScriptRepository,
        video_repo: VideoRepository,
        qc_repo: QcReviewRepository,
        judge: QcJudge,
        video_spec,
        phase: str = "full",   # "script" (pre-video) | "video" (post-video) | "full"
    ) -> None:
        self._profiles = profile_service
        self._script_repo = script_repo
        self._video_repo = video_repo
        self._qc_repo = qc_repo
        self._judge = judge
        self._spec = video_spec
        self._phase = phase

    def run(self, job: CreativeJob) -> AgentResult:
        script = self._script_repo.get(job.script_id) if job.script_id else None
        if script is None:
            raise NotFoundError("missing script for QC")

        rules = self._profiles.load().rules
        codes: list[str] = []
        reasons: list[str] = []
        text = (script.text or "").strip()

        do_script = self._phase in ("script", "full")
        do_video = self._phase in ("video", "full")

        if do_script:
            self._check_script(text, script, rules, codes, reasons)

        video = None
        if do_video:
            video = self._video_repo.get(job.video_id) if job.video_id else None
            if video is None:
                raise NotFoundError("missing video for QC")
            self._check_video(video, rules, codes, reasons)

        rule_score = max(0.0, 1.0 - 0.25 * len(codes))
        reviewer = "rules"
        score = rule_score

        # Qualitative LLM judge — script-content check, so it runs in the SCRIPT
        # phase (before any video is generated). Skipped if the script is empty.
        if do_script and "SCRIPT_EMPTY" not in codes:
            judgement = self._judge.evaluate(
                text,
                duration_seconds=video.duration_seconds if video else None,
                aspect_ratio=video.aspect_ratio if video else "9:16",
            )
            if judgement is not None:
                reviewer = "rules+llm"
                score = min(rule_score, judgement.score)
                for c in judgement.codes:
                    if c not in codes:
                        codes.append(c)
                reasons.extend(judgement.reasons)
                logger.info("QC judge: approve=%s codes=%s", judgement.approve, judgement.codes)

        verdict = QcVerdict.REJECT if codes else QcVerdict.APPROVE
        if not codes:
            reasons.append(f"Passed all {self._phase} checks.")

        self._qc_repo.add(
            job_id=job.id,
            product_id=job.product_id,
            script_id=script.id,
            video_id=video.id if video else None,
            verdict=verdict,
            score=score,
            reasons=reasons,
            failure_codes=codes,
            reviewer=reviewer,
            attempt=job.attempt,
        )
        logger.info(
            "QC[%s] verdict=%s reviewer=%s score=%.2f codes=%s",
            self._phase, verdict.value, reviewer, score, codes,
        )

        if verdict is QcVerdict.REJECT:
            next_status = JobStatus.REJECTED
        elif self._phase == "script":
            next_status = JobStatus.SCRIPT_APPROVED
        else:
            next_status = JobStatus.APPROVED
        return AgentResult(
            ok=True,
            next_status=next_status,
            data={"verdict": verdict.value, "codes": codes, "reasons": reasons},
        )

    # ---- checks ----
    def _check_script(self, text, script, rules, codes, reasons) -> None:
        if not text:
            codes.append("SCRIPT_EMPTY")
            reasons.append("Script text is empty.")
        if script.word_count > rules.max_words:
            codes.append("SCRIPT_TOO_LONG")
            reasons.append(f"Script is {script.word_count} words (max {rules.max_words}).")
        elif rules.min_words and text and script.word_count < rules.min_words:
            codes.append("SCRIPT_TOO_SHORT")
            reasons.append(
                f"Script is only {script.word_count} words (min {rules.min_words}); "
                "too short to fill the video."
            )

        lowered = text.lower()
        if rules.cta_keywords and not any(k in lowered for k in rules.cta_keywords):
            codes.append("MISSING_CTA")
            reasons.append("No call-to-action keyword found in the script.")

        for claim in rules.banned_claims:
            if claim.lower() in lowered:
                codes.append("BANNED_CLAIM")
                reasons.append(f"Script contains a banned claim: '{claim}'.")
                break

    def _check_video(self, video, rules, codes, reasons) -> None:
        video_present = bool(
            video.local_path and os.path.exists(video.local_path) and os.path.getsize(video.local_path) > 0
        )
        if not video_present:
            codes.append("VIDEO_MISSING")
            reasons.append("Video file is missing or empty.")
        else:
            self._check_video_specs(video.local_path, codes, reasons)

        if video.duration_seconds is not None and not (
            rules.min_seconds <= video.duration_seconds <= rules.max_seconds
        ):
            codes.append("DURATION_OUT_OF_RANGE")
            reasons.append(
                f"Video is {video.duration_seconds:.0f}s "
                f"(allowed {rules.min_seconds:.0f}-{rules.max_seconds:.0f}s)."
            )

    def _check_video_specs(self, path: str, codes: list[str], reasons: list[str]) -> None:
        """Enforce platform delivery specs on the downloaded file."""
        spec = self._spec
        # File size (dependency-free).
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > spec.max_file_mb:
            codes.append("VIDEO_TOO_LARGE")
            reasons.append(f"Video is {size_mb:.1f}MB (max {spec.max_file_mb:.0f}MB).")
        # Container format (dependency-free).
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if spec.allowed_formats and ext not in spec.allowed_formats:
            codes.append("BAD_FORMAT")
            reasons.append(f"Format '.{ext}' not in {list(spec.allowed_formats)}.")
        # Resolution + fps (optional; needs ffprobe). Skipped silently if absent.
        if spec.check_media:
            from app.services.media_probe import probe_media

            meta = probe_media(path)
            if meta:
                if (meta["width"], meta["height"]) != (spec.width, spec.height):
                    codes.append("BAD_RESOLUTION")
                    reasons.append(
                        f"Resolution {meta['width']}x{meta['height']} != "
                        f"{spec.width}x{spec.height}."
                    )
                if spec.fps and abs(meta["fps"] - spec.fps) > 1:
                    codes.append("BAD_FPS")
                    reasons.append(f"Frame rate {meta['fps']}fps != {spec.fps}fps.")
