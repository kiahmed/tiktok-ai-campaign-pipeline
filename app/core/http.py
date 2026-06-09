"""Helpers for turning low-level HTTP failures into domain exceptions.

Providers talk to the network with ``requests``. Transport failures (DNS
resolution, connection refused, timeouts, TLS errors, malformed JSON) surface
as ``requests.RequestException`` subclasses — vendor/transport detail that the
service and API layers must never see. This decorator converts them into the
appropriate :class:`~app.core.exceptions.ProviderError`, so everything above the
provider boundary only deals with the domain exception hierarchy.

Place it ABOVE ``@with_retry()`` so translation happens only after retries are
exhausted:

    @translate_network_errors(VideoGenerationError)
    @with_retry()
    def _submit_job(self, ...): ...
"""
from __future__ import annotations

import functools
from typing import Callable, Type, TypeVar

import requests

from app.core.exceptions import ProviderError

F = TypeVar("F", bound=Callable)


def translate_network_errors(error_cls: Type[ProviderError]) -> Callable[[F], F]:
    """Re-raise ``requests`` transport errors as ``error_cls`` (a ProviderError)."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except requests.RequestException as exc:
                # First positional arg is ``self`` for the provider methods we wrap.
                provider = getattr(args[0], "name", None) if args else None
                raise error_cls(
                    f"network error contacting provider: {exc}", provider=provider
                ) from exc

        return wrapper  # type: ignore[return-value]

    return decorator
