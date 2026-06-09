"""Shared retry strategy for flaky external calls.

A single decorator is used by every provider so retry/backoff behaviour is
consistent and tunable in one place. Built on tenacity.
"""
from __future__ import annotations

import logging
from typing import Callable, TypeVar

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

_logger = logging.getLogger("retry")

T = TypeVar("T")

# Exceptions that are worth retrying — transient network / timeout problems.
_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def with_retry(
    *,
    attempts: int = 4,
    min_wait: float = 1.0,
    max_wait: float = 20.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: retry the wrapped call on transient network errors.

    Uses exponential backoff between attempts. Non-network errors (e.g. a 4xx
    surfaced as a ``ProviderError``) are *not* retried — they will not fix
    themselves.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=min_wait, max=max_wait),
        retry=retry_if_exception_type(_RETRYABLE),
        before_sleep=before_sleep_log(_logger, logging.WARNING),
    )
