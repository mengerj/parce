"""Mock-based tests for the orchestration flow in main.py.

These tests do NOT require Azure credentials or network access: the CELLxGENE
adapter's Census/EuropePMC calls are mocked, while the real adapter and
normalizer run end to end. The pipeline is deterministic — there is no LLM.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from parce.main import run

_MOCK_PAPER = {
    "doi": "10.1234/mock",
    "title": "Mock Study",
    "abstract": "We studied cells.",
}

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


def _patch_network(paper=_MOCK_PAPER, cellxgene=_MOCK_CELLXGENE):
    return (
        patch("parce.sources.cellxgene.fetch_paper_metadata", return_value=paper),
        patch("parce.sources.cellxgene.fetch_cellxgene_datasets", return_value=cellxgene),
    )


class TestRunOrchestration:
    def test_full_pipeline(self, tmp_path):
        p_paper, p_cx = _patch_network()
        with p_paper, p_cx, patch("parce.main._OUTPUT_DIR", tmp_path):
            run(doi="10.1234/mock")

        out_file = tmp_path / "output.json"
        assert out_file.exists()

        kg = json.loads(out_file.read_text())
        assert len(kg["studies"]) == 1
        assert kg["studies"][0]["study_id"] == "10.1234/mock"
        assert kg["studies"][0]["title"] == "Mock Study"
        assert kg["studies"][0]["source"] == "CELLxGENE"
        # The canonical KG never stores a narrative.
        assert "experimental_narrative" not in kg["studies"][0]
        assert len(kg["datasets"]) == 1
        assert len(kg["biological_entities"]) > 0
        assert len(kg["edges"]) > 0

    def test_fetch_called_with_doi(self, tmp_path):
        p_paper, p_cx = _patch_network()
        with p_paper as mock_paper, p_cx as mock_cx, patch("parce.main._OUTPUT_DIR", tmp_path):
            run(doi="10.1234/mock")

        mock_paper.assert_called_once_with("10.1234/mock")
        mock_cx.assert_called_once_with("10.1234/mock", max_workers=4)

    def test_no_datasets_writes_nothing(self, tmp_path):
        empty = {"doi": "10.1234/mock", "datasets": [], "error": "No datasets found"}
        p_paper, p_cx = _patch_network(cellxgene=empty)
        with p_paper, p_cx, patch("parce.main._OUTPUT_DIR", tmp_path):
            run(doi="10.1234/mock")

        assert not (tmp_path / "output.json").exists()
