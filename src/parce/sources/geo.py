"""GEO (NCBI Gene Expression Omnibus) source adapter — deterministic fetch only.

The adapter pulls a GEO **Series** (``GSEnnnnn``) and its **Samples** (``GSMnnnnn``)
as SOFT-format text from the public GEO accession endpoint, parses the fields a
normalizer needs, and emits a source-shaped
:class:`~parce.models.raw_record.RawRecord`. It performs **no interpretation**:
the messy, semi-structured ``!Sample_characteristics_ch1`` lines are carried
verbatim in the payload. Turning that free text into canonical design covariates
is the matching agent-backed :class:`~parce.normalize.geo.GeoNormalizer`'s job —
this is GEO's reason for being the first LLM-using source (docs/ARCHITECTURE.md §2).

Why a direct SOFT fetch + a small parser rather than GEOparse: the only fields we
need (series title/type/summary, and per-sample title/organism/source/
characteristics/supplementary-file) are a handful of ``!``-prefixed keys in the
SOFT text. A focused ~40-line parser keeps the dependency surface minimal and the
parse fully unit-testable against a captured fixture, with no large data-table
download (``view=quick`` omits the matrices).

The GEO endpoint is the only network IO here; it is wrapped in the shared
:func:`parce.sources._retry.with_retries` helper.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

from parce.models.raw_record import RawRecord
from parce.sources._retry import with_retries

logger = logging.getLogger(__name__)

SOURCE_NAME = "GEO"

_GEO_ACC_URL = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
_DEFAULT_TIMEOUT = 60
#: Bound the per-series sample count handed downstream so a 1000-sample series
#: does not balloon a single LLM extraction call. Truncation is flagged on the
#: payload and logged (never silent).
_DEFAULT_MAX_SAMPLES = 200

_GSE_RE = re.compile(r"^GSE\d+$", re.IGNORECASE)


def _looks_like_series(query: str) -> bool:
    """True if ``query`` is a GEO Series accession (``GSEnnnnn``)."""
    return bool(_GSE_RE.match(query.strip()))


class GeoAdapter:
    """:class:`~parce.sources.base.SourceAdapter` for NCBI GEO Series.

    Deterministic: it fetches and parses metadata only. ``email``/``api_key`` are
    optional NCBI E-utilities courtesy parameters (higher rate limits, contact on
    file); pass them from settings in production, omit them in tests.
    """

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        email: str | None = None,
        api_key: str | None = None,
        base_url: str = _GEO_ACC_URL,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._email = email
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout

    def discover(self, query: str) -> list[str]:
        """Resolve ``query`` to GEO Series references the adapter can ``fetch``.

        A GEO Series accession is the reference, so ``discover`` is the identity on
        a ``GSEnnnnn`` string (mirroring the CELLxGENE adapter's DOI identity).
        Free-text keyword search via Entrez ``esearch`` is backlog
        (see docs/ROADMAP.md); a non-accession query is rejected here rather than
        silently returning nothing useful.
        """
        q = query.strip()
        if not _looks_like_series(q):
            logger.warning(
                "GEO discover only supports a Series accession (GSEnnnnn); got %r", query
            )
            return []
        return [q.upper()]

    def fetch(self, ref: str, *, max_samples: int = _DEFAULT_MAX_SAMPLES) -> RawRecord:
        """Fetch one GEO Series accession into a source-shaped ``RawRecord``.

        The payload carries the parsed ``series`` fields and a ``samples`` list
        (each with its raw ``characteristics`` lines). When more than
        ``max_samples`` samples exist, the list is truncated and ``truncated`` is
        set on the payload (and logged).
        """
        soft = self._fetch_soft(ref)
        series, samples = _parse_soft(soft)

        truncated = len(samples) > max_samples
        if truncated:
            logger.warning(
                "GEO series %s has %d samples; truncating to %d for extraction",
                ref,
                len(samples),
                max_samples,
            )
            samples = samples[:max_samples]

        payload: dict[str, Any] = {
            "series": series,
            "samples": samples,
            "truncated": truncated,
        }
        logger.info("Fetched GEO series %s: samples=%d truncated=%s", ref, len(samples), truncated)

        return RawRecord(
            source=self.source_name,
            study_id=ref.upper(),
            title=series.get("title", ""),
            payload=payload,
        )

    def _fetch_soft(self, accession: str) -> str:
        """Fetch the full SOFT text (series + samples) for ``accession``."""
        params: dict[str, str] = {
            "acc": accession,
            "targ": "all",  # series + platform + all samples in one document
            "form": "text",
            "view": "quick",  # metadata headers only; omit the big data matrices
        }
        if self._email:
            params["email"] = self._email
        if self._api_key:
            params["api_key"] = self._api_key

        def _request() -> requests.Response:
            resp = requests.get(self._base_url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp

        resp = with_retries(_request, description=f"GEO SOFT fetch acc={accession}")
        return resp.text


# -- SOFT parsing --------------------------------------------------------------
# SOFT is a flat, line-oriented format. Entity blocks open with a ``^`` marker
# (``^SERIES``, ``^PLATFORM``, ``^SAMPLE``); within a block, metadata lines are
# ``!Key = value`` and a key may repeat (summary, type, characteristics).

_SERIES_SINGLE = {
    "!Series_title": "title",
    "!Series_overall_design": "overall_design",
    "!Series_geo_accession": "geo_accession",
}
_SERIES_MULTI = {
    "!Series_summary": "summary",
    "!Series_type": "type",
    "!Series_pubmed_id": "pubmed_id",
}

_SAMPLE_SINGLE = {
    "!Sample_title": "title",
    "!Sample_geo_accession": "sample_id",
    "!Sample_source_name_ch1": "source_name",
    "!Sample_organism_ch1": "organism",
    "!Sample_supplementary_file": "supplementary_file",
}


def _split_kv(line: str) -> tuple[str, str] | None:
    """Split a SOFT ``!Key = value`` (or ``!Key=value``) line; ``None`` if not one."""
    if not line.startswith("!"):
        return None
    key, sep, value = line.partition("=")
    if not sep:
        return None
    return key.strip(), value.strip()


def _parse_soft(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse SOFT text into ``(series_fields, samples)``.

    ``series_fields`` collapses single-valued keys to a string and multi-valued
    keys (``summary``/``type``/``pubmed_id``) to a list. Each sample dict carries
    its single-valued fields plus a ``characteristics`` list of the raw
    ``key: value`` strings (left for the LLM to normalize).
    """
    series: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None  # the SAMPLE block being filled, if any

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("^"):
            marker = line[1:].split("=", 1)[0].strip().upper()
            if marker == "SAMPLE":
                current = {"characteristics": []}
                samples.append(current)
            else:  # ^SERIES / ^PLATFORM — leave the sample context
                current = None
            continue

        kv = _split_kv(line)
        if kv is None:
            continue
        key, value = kv

        if current is not None:  # inside a SAMPLE block
            if key == "!Sample_characteristics_ch1":
                current["characteristics"].append(value)
            elif key in _SAMPLE_SINGLE:
                current.setdefault(_SAMPLE_SINGLE[key], value)
            continue

        # SERIES (or PLATFORM, which we ignore) context.
        if key in _SERIES_SINGLE:
            series.setdefault(_SERIES_SINGLE[key], value)
        elif key in _SERIES_MULTI:
            series.setdefault(_SERIES_MULTI[key], []).append(value)

    return series, samples
