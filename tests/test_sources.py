"""Unit tests for source adapters, the RawRecord model, and the protocols.

All Census/EuropePMC IO is mocked — these tests must stay offline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from parce.models.raw_record import RawRecord
from parce.normalize.base import Normalizer
from parce.normalize.cellxgene import CellxgeneNormalizer
from parce.sources.base import SourceAdapter
from parce.sources.cellxgene import CellxgeneAdapter

_MOCK_PAPER = {"doi": "10.1234/mock", "title": "Mock Study", "abstract": "We studied cells."}
_MOCK_CELLXGENE = {
    "doi": "10.1234/mock",
    "datasets": [
        {
            "dataset_id": "mock-ds-1",
            "dataset_title": "Mock Dataset",
            "h5ad_uri": "s3://bucket/mock-ds-1.h5ad",
            "modality": "10x 3' v3",
            "cell_count": 100,
            "ontology_summary": {
                "organism": "Homo sapiens",
                "modality": "10x 3' v3",
                "tissues": [{"name": "blood", "ontology_id": "UBERON:0000178"}],
                "diseases": [],
                "assays": [{"name": "10x 3' v3", "ontology_id": "EFO:0009922"}],
            },
        }
    ],
}


class TestRawRecord:
    def test_minimal(self):
        record = RawRecord(source="CELLxGENE", study_id="10.1234/x")
        assert record.title == ""
        assert record.payload == {}

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            RawRecord(source="GEO", study_id="GSE1", bogus=True)


class TestCellxgeneAdapter:
    def test_source_name(self):
        assert CellxgeneAdapter().source_name == "CELLxGENE"

    def test_discover_is_identity_on_doi(self):
        assert CellxgeneAdapter().discover("10.1234/mock") == ["10.1234/mock"]

    def test_fetch_builds_raw_record(self):
        with (
            patch("parce.sources.cellxgene.fetch_paper_metadata", return_value=_MOCK_PAPER),
            patch("parce.sources.cellxgene.fetch_cellxgene_datasets", return_value=_MOCK_CELLXGENE),
        ):
            record = CellxgeneAdapter().fetch("10.1234/mock")

        assert record.source == "CELLxGENE"
        assert record.study_id == "10.1234/mock"
        assert record.title == "Mock Study"
        assert len(record.payload["datasets"]) == 1
        assert record.payload["datasets"][0]["dataset_id"] == "mock-ds-1"
        assert "error" not in record.payload

    def test_fetch_propagates_no_match_error(self):
        empty = {"doi": "10.1234/none", "datasets": [], "error": "No datasets found"}
        with (
            patch(
                "parce.sources.cellxgene.fetch_paper_metadata",
                return_value={"doi": "10.1234/none", "title": "", "abstract": ""},
            ),
            patch("parce.sources.cellxgene.fetch_cellxgene_datasets", return_value=empty),
        ):
            record = CellxgeneAdapter().fetch("10.1234/none")

        assert record.payload["datasets"] == []
        assert record.payload["error"] == "No datasets found"

    def test_fetch_passes_max_workers(self):
        with (
            patch("parce.sources.cellxgene.fetch_paper_metadata", return_value=_MOCK_PAPER),
            patch(
                "parce.sources.cellxgene.fetch_cellxgene_datasets", return_value=_MOCK_CELLXGENE
            ) as mock_fetch,
        ):
            CellxgeneAdapter().fetch("10.1234/mock", max_workers=2)

        mock_fetch.assert_called_once_with("10.1234/mock", max_workers=2)


class TestProtocolConformance:
    def test_adapter_satisfies_source_adapter(self):
        assert isinstance(CellxgeneAdapter(), SourceAdapter)

    def test_normalizer_satisfies_normalizer(self):
        assert isinstance(CellxgeneNormalizer(), Normalizer)
