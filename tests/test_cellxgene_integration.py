"""Integration test for CELLxGENE Census querying.

This test is intended to catch schema/filter/organism mismatches early.
It requires network access and will take time to run.

Run explicitly with:
    pytest -m integration -k cellxgene
"""

from __future__ import annotations

import json

import pytest

from parce.tools.cellxgene_fetcher import fetch_cellxgene_data, fetch_cellxgene_datasets

pytestmark = pytest.mark.integration

_TEST_DOI = "10.1038/s41467-025-63202-x"


class TestCellxgeneFetcherTool:
    """Test the @tool-decorated JSON-string version."""

    async def test_fetch_cellxgene_data_returns_datasets(self):
        raw = fetch_cellxgene_data(_TEST_DOI)
        payload = json.loads(raw)

        assert payload["doi"] == _TEST_DOI
        assert "datasets" in payload
        assert len(payload["datasets"]) > 0
        assert "ontology_summary" in payload["datasets"][0]

        any_terms = any(
            (
                d.get("ontology_summary", {}).get("cell_types")
                or d.get("ontology_summary", {}).get("tissues")
                or d.get("ontology_summary", {}).get("diseases")
                or d.get("ontology_summary", {}).get("assays")
            )
            for d in payload["datasets"]
        )
        assert any_terms, "No ontology terms extracted from any matched dataset"


class TestCellxgeneFetcherCore:
    """Test the dict-returning core function."""

    async def test_fetch_cellxgene_datasets_structured_terms(self):
        payload = fetch_cellxgene_datasets(_TEST_DOI)

        assert payload["doi"] == _TEST_DOI
        assert len(payload["datasets"]) > 0

        ds = payload["datasets"][0]
        assert "modality" in ds
        assert ds["modality"] != "", "modality should be populated"

        ontology = ds.get("ontology_summary", {})
        for category in ("cell_types", "tissues", "diseases", "assays"):
            terms = ontology.get(category, [])
            if terms:
                assert isinstance(terms[0], dict), f"{category} terms should be dicts"
                assert "name" in terms[0]
                assert "ontology_id" in terms[0]

    async def test_modality_populated(self):
        payload = fetch_cellxgene_datasets(_TEST_DOI)
        any_modality = any(
            ds.get("modality") and ds["modality"] != "unknown" for ds in payload["datasets"]
        )
        assert any_modality, "At least one dataset should have a known modality"
