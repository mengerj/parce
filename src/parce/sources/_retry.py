"""Generic bounded-retry-with-jittered-backoff for source-adapter network IO.

Source adapters call out to external repositories (CELLxGENE Census, EuropePMC,
and -- later -- GEO and PRIDE) over flaky networks. They share this one retry
helper instead of each rolling its own: it retries only *transient* failures
(network timeouts, dropped connections, HTTP 429/5xx) with exponential backoff
and full jitter, and re-raises everything else immediately.

It is deliberately **not** coupled to any one client library. Transient
detection is expressed in terms of stdlib exceptions plus ``requests`` errors,
which every current adapter speaks; nothing here imports Azure or Census. This
replaces the Azure-keyed ``_is_transient``/``_backoff_delay`` helpers that used
to live in ``main.py`` for the (now-deprecated) LLM call.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Tuning knobs (module-level so callers and tests can reason about the bounds).
DEFAULT_MAX_ATTEMPTS = 4
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0

# HTTP status codes worth retrying: rate-limiting plus the standard 5xx faults.
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Stdlib exceptions that signal a transient network/IO fault. (TimeoutError and
# ConnectionError are themselves OSError subclasses; listed for clarity.)
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
)


def _status_code(exc: BaseException) -> int | None:
    """Best-effort HTTP status code carried by a ``requests`` error, else None."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def is_transient(exc: BaseException) -> bool:
    """Return True if *exc* looks transient and is worth retrying.

    Covers ``requests`` connection/timeout errors, ``requests`` HTTP errors
    carrying a 429/5xx status, and stdlib ``TimeoutError``/``ConnectionError``/
    ``OSError``. Every ``requests`` exception is itself an ``OSError`` subclass,
    so they are classified here *first* -- otherwise the broad stdlib check
    below would wrongly retry a 404 or a malformed-URL error.
    """
    if isinstance(exc, requests.RequestException):
        if isinstance(exc, requests.HTTPError):
            return _status_code(exc) in _TRANSIENT_STATUS_CODES
        return isinstance(exc, requests.ConnectionError | requests.Timeout)
    return isinstance(exc, _TRANSIENT_EXCEPTIONS)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter for a zero-based *attempt* index."""
    ceiling = min(_BASE_DELAY * (2**attempt), _MAX_DELAY)
    return random.uniform(0, ceiling)


def with_retries(
    func: Callable[..., T],
    *args,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    description: str | None = None,
    **kwargs,
) -> T:
    """Call ``func(*args, **kwargs)``, retrying transient failures.

    Makes up to ``max_attempts`` total tries. On a transient error (see
    :func:`is_transient`) it sleeps with exponential backoff + full jitter and
    tries again; a non-transient error propagates immediately, and the final
    transient error is re-raised once attempts are exhausted.

    ``description`` labels the call in retry logs (defaults to ``func.__name__``,
    which is useful when wrapping a lambda).
    """
    label = description or getattr(func, "__name__", "call")
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if not is_transient(exc) or attempt == max_attempts - 1:
                raise
            delay = _backoff_delay(attempt)
            logger.warning(
                "Transient error calling %s (attempt %d/%d), retrying in %.1fs: %s",
                label,
                attempt + 1,
                max_attempts,
                delay,
                exc,
            )
            time.sleep(delay)

    # Reachable only when max_attempts < 1; the loop above otherwise always
    # returns on success or re-raises on the final attempt.
    raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
