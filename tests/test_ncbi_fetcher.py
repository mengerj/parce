"""Offline tests for EuropePMC fetcher retry wiring.

Verifies that ``fetch_paper_metadata`` routes its HTTP call through the shared
retry helper -- a transient failure is retried and the eventual success is
parsed. ``requests.get`` is mocked and backoff sleep is patched out, so no
network access or real delay occurs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from parce.sources import _retry
from parce.tools.ncbi_fetcher import fetch_paper_metadata

_PAYLOAD = {"resultList": {"result": [{"title": "A Study", "abstractText": "We measured."}]}}


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"HTTP {status_code}", response=response)


def _ok_response() -> MagicMock:
    resp = MagicMock(name="response")
    resp.raise_for_status.return_value = None
    resp.json.return_value = _PAYLOAD
    return resp


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch.object(_retry.time, "sleep"):
        yield


def test_retries_on_5xx_then_parses():
    failing = MagicMock(name="failing_response")
    failing.raise_for_status.side_effect = _http_error(503)

    with patch(
        "parce.tools.ncbi_fetcher.requests.get",
        side_effect=[failing, _ok_response()],
    ) as mock_get:
        result = fetch_paper_metadata("10.1234/mock")

    assert mock_get.call_count == 2
    assert result == {"doi": "10.1234/mock", "title": "A Study", "abstract": "We measured."}


def test_retries_on_connection_error_then_parses():
    with patch(
        "parce.tools.ncbi_fetcher.requests.get",
        side_effect=[requests.ConnectionError("refused"), _ok_response()],
    ) as mock_get:
        result = fetch_paper_metadata("10.1234/mock")

    assert mock_get.call_count == 2
    assert result["title"] == "A Study"
