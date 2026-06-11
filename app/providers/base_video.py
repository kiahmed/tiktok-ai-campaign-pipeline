"""Reusable base for video providers that follow a submit-then-poll workflow.

Most AI video vendors (Pexo, Creatify, Arcads, Kling, ...) work the same way:
POST a job, then GET its status until a download URL appears. This base
captures that flow once. Concrete providers only declare their endpoints and
how to read the vendor-specific JSON via small override hooks — Template Method
pattern. New providers therefore cost ~30 lines, not ~130.
"""
from __future__ import annotations

import logging
import time
from abc import abstractmethod

import requests

from app.core.entities import ProductInput, ScriptResult, VideoResult
from app.core.entities.profile import CreativeDirectives
from app.core.exceptions import ConfigurationError, VideoGenerationError
from app.core.http import translate_network_errors
from app.core.interfaces import VideoGenerator
from app.core.retry import with_retry


class PollingVideoProvider(VideoGenerator):
    # Subclasses must set these.
    name: str = "abstract"
    create_path: str = "/v1/videos"
    status_path: str = "/v1/videos/{job_id}"
    status_done: set[str] = {"completed", "succeeded", "success"}
    status_failed: set[str] = {"failed", "error", "cancelled"}

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout: int = 60,
        poll_interval: float = 10.0,
        max_poll_seconds: float = 600.0,
    ) -> None:
        if not api_key:
            raise ConfigurationError(f"{self.name} API key is not set")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._max_poll_seconds = max_poll_seconds
        self._log = logging.getLogger(f"provider.{self.name}")
        # Audit trail of API calls for the current generate() (see api_calls).
        self._calls: list[dict] = []

    def record_call(self, **entry) -> None:
        """Append one API-call record to the current generate()'s audit trail.

        Subclasses (and this base) call it to capture the exact request payload,
        resolved parameters and response so they can be stored per video.
        """
        entry.setdefault("provider", self.name)
        self._calls.append(entry)

    @staticmethod
    def _script_snapshot(script: ScriptResult) -> dict:
        return {
            "text": script.text,
            "visual_prompt": script.visual_prompt,
            "word_count": script.word_count,
            "provider": script.provider,
            "model": script.model,
        }

    def preview(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        """Dry run: build the request WITHOUT submitting or generating media.

        Returns {"payload": <what would be POSTed>, "calls": [audit trail]} so the
        script, prompts and exact API payload can be reviewed before spending
        credits. Providers with side-effecting payload builds (e.g. HeyGen image
        generation) override this to skip those.
        """
        self._calls = []
        self.record_call(method="SCRIPT", endpoint="(script)", request=self._script_snapshot(script))
        payload = self.build_payload(product, script, directives)
        self.record_call(method="PREVIEW (not sent)", endpoint=self.create_path, request=payload)
        return {"payload": payload, "calls": list(self._calls)}

    # ---- VideoGenerator contract ----
    def generate(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> VideoResult:
        self._calls = []  # fresh audit trail for this generation
        # Snapshot the exact script object the payload is built from, so the
        # script -> payload mapping is visible per video (quality checking).
        self.record_call(method="SCRIPT", endpoint="(script)", request=self._script_snapshot(script))
        self._log.info("Submitting %s video job for product=%s", self.name, product.name)
        job_id = self._submit_job(product, script, directives)
        self._log.info("%s job submitted id=%s; polling", self.name, job_id)
        url, duration = self._poll_until_ready(job_id)
        return VideoResult(
            download_url=url,
            provider=self.name,
            external_job_id=job_id,
            format="mp4",
            aspect_ratio="9:16",
            duration_seconds=duration,
            api_calls=list(self._calls),
        )

    # ---- hooks for subclasses ----
    @abstractmethod
    def build_payload(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> dict:
        """Return the JSON body for the create-job request."""

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def parse_job_id(self, data: dict) -> str | None:
        return data.get("id") or data.get("job_id") or (data.get("data") or {}).get("id")

    def parse_status(self, data: dict) -> tuple[str, str | None, float | None]:
        body = data.get("data", data)
        status = str(body.get("status", "")).lower()
        url = body.get("video_url") or body.get("download_url") or body.get("url")
        duration = body.get("duration") or body.get("duration_seconds")
        return status, url, float(duration) if duration else None

    # ---- shared implementation ----
    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _submit_job(
        self,
        product: ProductInput,
        script: ScriptResult,
        directives: CreativeDirectives | None = None,
    ) -> str:
        payload = self.build_payload(product, script, directives)
        resp = requests.post(
            f"{self._base_url}{self.create_path}",
            headers=self.auth_headers(),
            json=payload,
            timeout=self._timeout,
        )
        body = self._safe_body(resp)
        self.record_call(
            method="POST",
            endpoint=self.create_path,
            request=payload,
            status_code=resp.status_code,
            response=body,
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(
                f"submit failed HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        job_id = self.parse_job_id(resp.json())
        if not job_id:
            raise VideoGenerationError("no job id in submit response", provider=self.name)
        return str(job_id)

    @staticmethod
    def _safe_body(resp) -> dict:
        """Return a small, JSON-able snapshot of a response for the audit trail."""
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"body": data}
        except Exception:
            return {"text": (resp.text or "")[:500]}

    def _poll_until_ready(self, job_id: str) -> tuple[str, float | None]:
        waited = 0.0
        while waited <= self._max_poll_seconds:
            status, url, duration = self._check_status(job_id)
            self._log.debug("%s job %s status=%s", self.name, job_id, status)
            if status in self.status_done:
                if not url:
                    raise VideoGenerationError(
                        f"job {job_id} completed but no URL", provider=self.name
                    )
                self.record_call(
                    method="GET", endpoint=self.status_path, request={"job_id": job_id},
                    status_code=200,
                    response={"status": status, "video_url": url, "duration": duration},
                )
                return url, duration
            if status in self.status_failed:
                self.record_call(
                    method="GET", endpoint=self.status_path, request={"job_id": job_id},
                    status_code=200, response={"status": status},
                )
                raise VideoGenerationError(
                    f"job {job_id} failed with status={status}", provider=self.name
                )
            time.sleep(self._poll_interval)
            waited += self._poll_interval
        raise VideoGenerationError(
            f"job {job_id} timed out after {self._max_poll_seconds:.0f}s", provider=self.name
        )

    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _check_status(self, job_id: str) -> tuple[str, str | None, float | None]:
        resp = requests.get(
            f"{self._base_url}{self.status_path.format(job_id=job_id)}",
            headers=self.auth_headers(),
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise VideoGenerationError(
                f"status HTTP {resp.status_code}: {resp.text[:200]}", provider=self.name
            )
        return self.parse_status(resp.json())
