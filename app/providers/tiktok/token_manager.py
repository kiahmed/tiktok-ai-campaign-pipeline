"""TikTok access-token lifecycle: auto-refresh before expiry, persisted.

The TikTok access token expires, so a static token would eventually start
returning auth errors. This manager:

  * returns a currently-valid access token on demand (``valid_token``),
  * refreshes it via the OAuth ``refresh_token`` grant when it's near expiry,
  * persists the rotated token + new expiry to a JSON store so it survives
    restarts (refresh tokens rotate on TikTok, so the latest must be kept),
  * is thread-safe (the hourly monitor runs on a separate thread), and
  * degrades to a plain static token when no refresh credentials are supplied
    (e.g. long-lived Marketing-API tokens that never expire).

NOTE: TikTok's OAuth endpoint/field names can vary by app type. They're
isolated as constants/one method here — adjust ``_REFRESH_PATH`` / the payload
if your app differs.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import requests

from app.core.exceptions import AdPlatformError, ConfigurationError
from app.core.http import translate_network_errors
from app.core.retry import with_retry

logger = logging.getLogger("provider.tiktok.token")

# TikTok error codes that mean "token invalid/expired" -> force a refresh.
AUTH_ERROR_CODES = {40105, 40100, 40102}


class TikTokTokenManager:
    name = "tiktok"
    _REFRESH_PATH = "/oauth2/access_token/"

    def __init__(
        self,
        *,
        app_id: str,
        secret: str,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        base_url: str,
        store_path: str = "config/tiktok_token.json",
        timeout: int = 30,
        refresh_buffer: float = 300.0,
    ) -> None:
        self._app_id = app_id
        self._secret = secret
        self._base = base_url.rstrip("/")
        self._store = store_path
        self._timeout = timeout
        self._buffer = refresh_buffer
        self._lock = threading.Lock()

        # The persisted store is the source of truth once it exists (it holds
        # rotated tokens); otherwise seed from the supplied (.env) values.
        persisted = self._load()
        if persisted:
            self._access_token = persisted.get("access_token", access_token)
            self._refresh_token = persisted.get("refresh_token", refresh_token)
            self._expires_at = float(persisted.get("expires_at", expires_at or 0))
        else:
            self._access_token = access_token
            self._refresh_token = refresh_token
            self._expires_at = float(expires_at or 0)
            if self._can_refresh():
                self._save()

    # ---- public ----
    def valid_token(self) -> str:
        """Return a valid access token, refreshing first if it's near expiry."""
        with self._lock:
            if self._can_refresh() and self._is_expiring():
                self._refresh_locked()
            return self._access_token

    def invalidate(self) -> None:
        """Mark the token expired so the next ``valid_token`` refreshes it.

        Called reactively when TikTok reports an auth-error code.
        """
        with self._lock:
            self._expires_at = 0.0

    # ---- internals ----
    def _can_refresh(self) -> bool:
        return bool(self._app_id and self._secret and self._refresh_token)

    def _is_expiring(self) -> bool:
        return (not self._access_token) or time.time() >= (self._expires_at - self._buffer)

    def _refresh_locked(self) -> None:
        if not self._can_refresh():
            raise ConfigurationError(
                "TikTok token refresh needs TIKTOK_APP_ID, TIKTOK_APP_SECRET, TIKTOK_REFRESH_TOKEN"
            )
        logger.info("Refreshing TikTok access token")
        data = self._call_refresh()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token") or self._refresh_token
        expires_in = float(data.get("expires_in") or 86400)
        self._expires_at = time.time() + expires_in
        self._save()
        logger.info("TikTok token refreshed (expires_in=%.0fs)", expires_in)

    @translate_network_errors(AdPlatformError)
    @with_retry()
    def _call_refresh(self) -> dict:
        resp = requests.post(
            f"{self._base}{self._REFRESH_PATH}",
            json={
                "app_id": self._app_id,
                "secret": self._secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise AdPlatformError(
                f"token refresh HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        body = resp.json()
        if body.get("code") not in (0, None):
            raise AdPlatformError(
                f"token refresh failed code={body.get('code')} msg={body.get('message')}",
                provider=self.name,
            )
        data = body.get("data") or {}
        if not data.get("access_token"):
            raise AdPlatformError(f"no access_token in refresh response: {body}", provider=self.name)
        return data

    def _load(self) -> dict | None:
        if not os.path.exists(self._store):
            return None
        try:
            with open(self._store, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read TikTok token store %s", self._store)
            return None

    def _save(self) -> None:
        try:
            directory = os.path.dirname(self._store)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self._store, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "access_token": self._access_token,
                        "refresh_token": self._refresh_token,
                        "expires_at": self._expires_at,
                    },
                    fh,
                )
        except OSError as exc:
            logger.warning("Could not persist TikTok token: %s", exc)
