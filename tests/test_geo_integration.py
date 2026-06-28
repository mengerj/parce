"""Live integration tests for the GEO vertical slice. Excluded from CI.

Two tiers, both marked ``integration``:

* the GEO **fetch/parse** test hits only the public GEO endpoint (no credentials);
* the **extraction** test additionally needs Azure (an ``az login`` session + the
  ``AZURE_AI_*`` settings) and is skipped when those are absent.

Run with::

    uv run pytest -m integration tests/test_geo_integration.py
"""

from __future__ import annotations

import os

import pytest

from parce.normalize.geo import GeoNormalizer
from parce.sources.geo import GeoAdapter

pytestmark = pytest.mark.integration

# A small, stable, public GEO series used as the live fixture.
_GSE = "GSE10072"


class TestLiveGeoFetch:
    def test_fetch_real_series(self):
        record = GeoAdapter().fetch(_GSE, max_samples=5)
        assert record.source == "GEO"
        assert record.study_id == _GSE
        assert record.title  # series has a title
        samples = record.payload["samples"]
        assert 1 <= len(samples) <= 5
        # Real GEO samples carry organism + characteristics.
        assert samples[0]["organism"] == "Homo sapiens"
        assert samples[0]["characteristics"]


def _azure_configured() -> bool:
    return bool(os.environ.get("AZURE_AI_PROJECT_ENDPOINT"))


@pytest.mark.skipif(not _azure_configured(), reason="Azure settings/credentials not configured")
class TestLiveGeoExtraction:
    def test_fetch_extract_normalize(self):
        # Deferred import so collection does not require the Azure deps to resolve.
        from parce.agent.extraction import AzureExtractionAgent
        from parce.ontology import OntologyResolver

        record = GeoAdapter().fetch(_GSE, max_samples=5)
        normalizer = GeoNormalizer(AzureExtractionAgent(), resolver=OntologyResolver())
        kg = normalizer.normalize(record)

        assert len(kg.studies) == 1
        assert kg.studies[0].source == "GEO"
        assert len(kg.samples) >= 1
        # No data-inferred annotations ever appear.
        assert all(not e.ontology_id.startswith("CL:") for e in kg.biological_entities)
