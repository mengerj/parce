"""Offline unit tests for the shared source-adapter retry helper.

These tests never touch the network: ``with_retries`` is driven with mocks, and
``time.sleep`` is patched out so backoff does not actually wait.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from parce.sources import _retry
from parce.sources._retry import is_transient, with_retries


def _http_error(status_code: int) -> requests.HTTPError:
    """Build a requests.HTTPError carrying a response with *status_code*."""
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"HTTP {status_code}", response=response)


class TestIsTransient:
    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("slow"),
            ConnectionError("dropped"),
            OSError("io"),
            requests.ConnectionError("refused"),
            requests.Timeout("timed out"),
            requests.ReadTimeout("read timed out"),
            _http_error(429),
            _http_error(500),
            _http_error(503),
        ],
    )
    def test_transient(self, exc):
        assert is_transient(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [
            ValueError("bad value"),
            KeyError("missing"),
            _http_error(404),
            _http_error(400),
            # requests errors that are OSError subclasses but NOT transient:
            requests.exceptions.MissingSchema("no scheme"),
            requests.exceptions.InvalidURL("bad url"),
        ],
    )
    def test_not_transient(self, exc):
        assert is_transient(exc) is False


class TestWithRetries:
    @pytest.fixture(autouse=True)
    def _no_sleep(self):
        # Keep the suite fast and offline: never actually sleep during backoff.
        with patch.object(_retry.time, "sleep") as sleep:
            yield sleep

    def test_returns_immediately_on_success(self):
        func = MagicMock(return_value="ok")
        assert with_retries(func, 1, 2, key="v") == "ok"
        func.assert_called_once_with(1, 2, key="v")

    def test_retries_transient_then_succeeds(self, _no_sleep):
        func = MagicMock(side_effect=[requests.ConnectionError("boom"), "ok"])
        assert with_retries(func) == "ok"
        assert func.call_count == 2
        _no_sleep.assert_called_once()  # exactly one backoff between the two tries

    def test_reraises_non_transient_immediately(self):
        func = MagicMock(side_effect=ValueError("nope"))
        with pytest.raises(ValueError, match="nope"):
            with_retries(func)
        func.assert_called_once()

    def test_exhausts_attempts_then_reraises(self, _no_sleep):
        func = MagicMock(side_effect=TimeoutError("persistent"))
        with pytest.raises(TimeoutError, match="persistent"):
            with_retries(func, max_attempts=3)
        assert func.call_count == 3
        assert _no_sleep.call_count == 2  # sleeps between attempts, not after the last

    def test_retries_http_5xx(self, _no_sleep):
        func = MagicMock(side_effect=[_http_error(503), "ok"])
        assert with_retries(func, max_attempts=2) == "ok"
        assert func.call_count == 2

    def test_does_not_retry_http_404(self):
        func = MagicMock(side_effect=_http_error(404))
        with pytest.raises(requests.HTTPError):
            with_retries(func)
        func.assert_called_once()

    def test_invalid_max_attempts_raises(self):
        func = MagicMock(return_value="never")
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            with_retries(func, max_attempts=0)
        func.assert_not_called()
