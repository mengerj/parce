"""Stub tool for fetching experiment metadata from NCBI GEO.

Replace the mock implementation with real GEO E-utilities / Entrez API calls
once the core agent loop is validated.
"""

from __future__ import annotations

import json
from typing import Annotated

from agent_framework import tool
from pydantic import Field

_MOCK_METADATA = {
    "GSE164378": {
        "accession": "GSE164378",
        "title": "Single-cell multi-omic profiling of human T cells during anti-PD-1 therapy",
        "organism": "Homo sapiens",
        "platform": "Illumina NovaSeq 6000",
        "summary": (
            "Peripheral blood and tumor-infiltrating T cells were profiled "
            "using paired scRNA-seq and scATAC-seq before and after anti-PD-1 "
            "immunotherapy in melanoma patients."
        ),
        "samples": [
            {
                "sample_id": "GSM5008101",
                "organism": "Homo sapiens",
                "cell_type": "CD8+ T cell",
                "tissue": "peripheral blood",
                "condition": "pre-treatment",
                "data_uris": [
                    {
                        "uri": "https://sra-pub-run-odp.s3.amazonaws.com/sra/SRR13568101/SRR13568101",
                        "file_type": "FASTQ",
                    }
                ],
            },
            {
                "sample_id": "GSM5008102",
                "organism": "Homo sapiens",
                "cell_type": "CD8+ T cell",
                "tissue": "tumor",
                "condition": "post-treatment",
                "data_uris": [
                    {
                        "uri": "https://sra-pub-run-odp.s3.amazonaws.com/sra/SRR13568102/SRR13568102",
                        "file_type": "FASTQ",
                    }
                ],
            },
        ],
    }
}


@tool
def fetch_geo_metadata(
    accession: Annotated[str, Field(description="GEO series accession ID (e.g. GSE164378)")],
) -> str:
    """Fetch experiment metadata from NCBI GEO for a given accession.

    Returns a JSON string containing the experiment title, organism,
    platform, summary, and per-sample metadata with data-file URIs.
    """
    if accession in _MOCK_METADATA:
        return json.dumps(_MOCK_METADATA[accession], indent=2)
    return json.dumps({"error": f"Accession {accession} not found (stub data only)."})
