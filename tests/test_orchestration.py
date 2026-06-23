"""Mock-based tests for the orchestration flow in main.py.

These tests do NOT require Azure credentials or network access.
They mock both data-fetching tools and the LLM agent to verify the
end-to-end assembly pipeline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parce.main import _build_narrative_prompt, run

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
                "cell_types": [{"name": "T cell", "ontology_id": "CL:0000084"}],
                "tissues": [{"name": "blood", "ontology_id": "UBERON:0000178"}],
                "diseases": [],
                "assays": [{"name": "10x 3' v3", "ontology_id": "EFO:0009922"}],
            },
        }
    ],
}


class TestBuildNarrativePrompt:
    def test_includes_title_and_abstract(self):
        prompt = _build_narrative_prompt(_MOCK_PAPER, _MOCK_CELLXGENE)
        assert "Mock Study" in prompt
        assert "We studied cells." in prompt

    def test_includes_dataset_info(self):
        prompt = _build_narrative_prompt(_MOCK_PAPER, _MOCK_CELLXGENE)
        assert "mock-ds-1" in prompt
        assert "T cell" in prompt
        assert "100" in prompt

    def test_includes_organism(self):
        prompt = _build_narrative_prompt(_MOCK_PAPER, _MOCK_CELLXGENE)
        assert "Homo sapiens" in prompt

    def test_empty_datasets(self):
        prompt = _build_narrative_prompt(_MOCK_PAPER, {"doi": "x", "datasets": []})
        assert "Mock Study" in prompt
        assert "CELLxGENE" not in prompt


class TestRunOrchestration:
    @pytest.fixture(autouse=True)
    def _mock_settings(self):
        # The agent is mocked, so real Azure config is irrelevant here. Patch
        # Settings so the test never reads the environment / .env file and stays
        # hermetic (CI has no .env). max_retries must be a real int for range().
        fake = MagicMock()
        fake.max_retries = 3
        with patch("parce.main.Settings", return_value=fake):
            yield fake

    @pytest.fixture
    def _mock_tools(self):
        with (
            patch("parce.main.fetch_paper_metadata", return_value=_MOCK_PAPER) as mock_paper,
            patch("parce.main.fetch_cellxgene_datasets", return_value=_MOCK_CELLXGENE) as mock_cx,
        ):
            yield mock_paper, mock_cx

    @pytest.fixture
    def _mock_agent(self):
        mock_result = MagicMock()
        mock_result.value = MagicMock()
        mock_result.value.experimental_narrative = "A mock narrative about T cells."
        mock_result.usage = None

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_agent)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("parce.main.create_narrative_agent", return_value=ctx):
            yield mock_agent

    async def test_full_pipeline(self, _mock_tools, _mock_agent, tmp_path):
        with patch("parce.main._OUTPUT_DIR", tmp_path):
            await run(doi="10.1234/mock")

        out_file = tmp_path / "output.json"
        assert out_file.exists()

        import json

        kg = json.loads(out_file.read_text())
        assert len(kg["studies"]) == 1
        assert kg["studies"][0]["study_id"] == "10.1234/mock"
        # The canonical KG no longer stores a narrative.
        assert "experimental_narrative" not in kg["studies"][0]
        assert len(kg["datasets"]) == 1
        assert len(kg["biological_entities"]) > 0
        assert len(kg["edges"]) > 0

    async def test_tools_called_with_doi(self, _mock_tools, _mock_agent, tmp_path):
        mock_paper, mock_cx = _mock_tools
        with patch("parce.main._OUTPUT_DIR", tmp_path):
            await run(doi="10.1234/mock")

        mock_paper.assert_called_once_with("10.1234/mock")
        mock_cx.assert_called_once_with("10.1234/mock")

    async def test_agent_called_with_response_format(self, _mock_tools, _mock_agent, tmp_path):
        from parce.models.graph_schema import NarrativeOutput

        with patch("parce.main._OUTPUT_DIR", tmp_path):
            await run(doi="10.1234/mock")

        call_kwargs = _mock_agent.run.call_args
        assert call_kwargs.kwargs.get("response_format") is NarrativeOutput
