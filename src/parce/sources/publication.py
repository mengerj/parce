"""Publication metadata helper: a study's title/abstract for a DOI via EuropePMC.

Shared by source adapters that need a study's *publication* title — for example
CELLxGENE, whose Census exposes per-dataset titles and the collection DOI but not
the publication title. EuropePMC's search endpoint is free and needs no API key.

This is a deterministic API call (no LLM), so it lives in ``sources/`` and is
covered by mypy like the rest of the stable core.
"""

from __future__ import annotations

import logging

import requests

from parce.sources._retry import with_retries

logger = logging.getLogger(__name__)

_EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def fetch_paper_metadata(doi: str) -> dict[str, str]:
    """Fetch publication title and abstract for ``doi`` from EuropePMC.

    Returns a dict with keys ``doi``, ``title`` and ``abstract``. If the DOI is
    not found, ``title``/``abstract`` are empty and an ``error`` key is added.
    """
    logger.info("Fetching paper metadata for DOI=%s", doi)

    def _request() -> requests.Response:
        # raise_for_status() lives inside the retried call so that a 429/5xx
        # surfaces as a transient HTTPError and is retried, not raised straight out.
        resp = requests.get(
            _EUROPEPMC_SEARCH_URL,
            params={
                "query": f"DOI:{doi}",
                "resultType": "core",
                "format": "json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp

    resp = with_retries(_request, description=f"EuropePMC search DOI={doi}")
    data = resp.json()

    results = data.get("resultList", {}).get("result", [])
    if not results:
        logger.warning("No publication found for DOI=%s", doi)
        return {
            "doi": doi,
            "title": "",
            "abstract": "",
            "error": f"No publication found for DOI {doi}",
        }

    paper = results[0]
    return {
        "doi": doi,
        "title": paper.get("title", ""),
        "abstract": paper.get("abstractText", ""),
    }
