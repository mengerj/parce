"""Tool for fetching publication title and abstract via the EuropePMC REST API.

Uses the free EuropePMC search endpoint (no API key required) to retrieve
core metadata for a given DOI.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

import requests
from agent_framework import tool
from pydantic import Field

logger = logging.getLogger(__name__)

_EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def fetch_paper_metadata(doi: str) -> dict:
    """Core function: fetch publication metadata and return a Python dict.

    This is the programmatic entry point used by the orchestrator.
    """
    logger.info("Fetching paper metadata for DOI=%s", doi)
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
    data = resp.json()

    results = data.get("resultList", {}).get("result", [])
    if not results:
        logger.warning("No publication found for DOI=%s", doi)
        return {"doi": doi, "title": "", "abstract": "", "error": f"No publication found for DOI {doi}"}

    paper = results[0]
    return {
        "doi": doi,
        "title": paper.get("title", ""),
        "abstract": paper.get("abstractText", ""),
    }


@tool
def fetch_paper_context(
    doi: Annotated[str, Field(description="Publication DOI (e.g. '10.1038/s41586-023-05869-0')")],
) -> str:
    """Fetch the title and abstract of a publication from EuropePMC.

    Returns a JSON string with keys ``doi``, ``title``, and ``abstract``.
    If the DOI is not found, returns an error message.
    """
    return json.dumps(fetch_paper_metadata(doi), separators=(",", ":"))
