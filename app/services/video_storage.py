"""Downloads generated videos to the local ``generated_videos/`` folder."""
from __future__ import annotations

import logging
import os

import requests

from app.core.exceptions import StorageError
from app.core.retry import with_retry

logger = logging.getLogger("service.storage")


class VideoStorageService:
    def __init__(self, storage_dir: str = "generated_videos", timeout: int = 120) -> None:
        self._dir = storage_dir
        self._timeout = timeout
        os.makedirs(self._dir, exist_ok=True)

    @with_retry()
    def download(self, url: str, file_name: str) -> str:
        """Stream ``url`` to ``<storage_dir>/<file_name>``; return the path."""
        dest = os.path.join(self._dir, file_name)
        logger.info("Downloading video -> %s", dest)
        try:
            with requests.get(url, stream=True, timeout=self._timeout) as resp:
                if resp.status_code >= 400:
                    raise StorageError(
                        f"download failed HTTP {resp.status_code} for {url}"
                    )
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
        except requests.RequestException as exc:
            raise StorageError(f"download error for {url}: {exc}") from exc

        if os.path.getsize(dest) == 0:
            os.remove(dest)
            raise StorageError(f"downloaded file was empty: {url}")
        logger.info("Saved video (%d bytes): %s", os.path.getsize(dest), dest)
        return dest
