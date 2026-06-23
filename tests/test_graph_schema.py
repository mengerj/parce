"""Unit tests for the Knowledge Graph Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    NarrativeOutput,
    PublicationNode,
)


class TestEntityType:
    def test_values(self):
        assert EntityType.DISEASE == "Disease"
        assert EntityType.CELL_TYPE == "CellType"
        assert EntityType.TISSUE == "Tissue"
        assert EntityType.SPECIES == "Species"
        assert EntityType.PERTURBATION == "Perturbation"
        assert EntityType.ASSAY == "Assay"

    def test_from_string(self):
        assert EntityType("Disease") is EntityType.DISEASE


class TestPublicationNode:
    def test_valid(self):
        pub = PublicationNode(
            doi="10.1038/s41586-023-05869-0",
            title="A study",
            abstract="An abstract.",
            experimental_narrative="Narrative text.",
        )
        assert pub.doi == "10.1038/s41586-023-05869-0"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            PublicationNode(
                doi="10.1234/test",
                title="T",
                abstract="A",
                experimental_narrative="N",
                extra="bad",
            )


class TestDatasetNode:
    def test_valid(self):
        ds = DatasetNode(
            dataset_id="abc-123",
            uri="s3://cellxgene-data-public/cell-census/h5ads/abc-123.h5ad",
            modality="scRNA-seq",
            cell_count=50000,
        )
        assert ds.cell_count == 50000

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            DatasetNode(dataset_id="x", uri="s3://x", modality="m", cell_count=1, oops=True)


class TestBiologicalEntityNode:
    def test_valid(self):
        entity = BiologicalEntityNode(
            entity_type=EntityType.CELL_TYPE,
            ontology_id="CL:0000084",
            name="T cell",
        )
        assert entity.entity_type == EntityType.CELL_TYPE

    def test_string_coercion(self):
        entity = BiologicalEntityNode(
            entity_type="Disease",
            ontology_id="MONDO:0005061",
            name="lung disease",
        )
        assert entity.entity_type is EntityType.DISEASE

    def test_invalid_entity_type(self):
        with pytest.raises(ValidationError):
            BiologicalEntityNode(entity_type="NotAType", ontology_id="X", name="bad")

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            BiologicalEntityNode(
                entity_type="Tissue", ontology_id="UBERON:0001062", name="t", foo="bar"
            )


class TestGraphEdge:
    def test_valid(self):
        edge = GraphEdge(
            source_id="abc-123",
            target_id="10.1038/s41586-023-05869-0",
            relation_type="EXTRACTED_FROM",
        )
        assert edge.relation_type == "EXTRACTED_FROM"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            GraphEdge(source_id="a", target_id="b", relation_type="R", weight=1.0)


class TestKnowledgeGraphOutput:
    def test_empty(self):
        kg = KnowledgeGraphOutput()
        assert kg.publications == []
        assert kg.edges == []

    def test_roundtrip_json(self):
        kg = KnowledgeGraphOutput(
            publications=[
                PublicationNode(
                    doi="10.1234/test",
                    title="Test",
                    abstract="Abstract.",
                    experimental_narrative="Narrative.",
                )
            ],
            datasets=[
                DatasetNode(
                    dataset_id="ds-1",
                    uri="s3://bucket/ds-1.h5ad",
                    modality="scRNA-seq",
                    cell_count=1000,
                )
            ],
            biological_entities=[
                BiologicalEntityNode(
                    entity_type=EntityType.CELL_TYPE,
                    ontology_id="CL:0000084",
                    name="T cell",
                )
            ],
            edges=[
                GraphEdge(
                    source_id="ds-1",
                    target_id="10.1234/test",
                    relation_type="EXTRACTED_FROM",
                )
            ],
        )
        json_str = kg.model_dump_json()
        restored = KnowledgeGraphOutput.model_validate_json(json_str)
        assert restored == kg

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            KnowledgeGraphOutput(metadata={"bad": True})


class TestNarrativeOutput:
    def test_valid(self):
        n = NarrativeOutput(experimental_narrative="A narrative.")
        assert n.experimental_narrative == "A narrative."

    def test_missing_field(self):
        with pytest.raises(ValidationError):
            NarrativeOutput()

    def test_roundtrip_json(self):
        n = NarrativeOutput(experimental_narrative="Test narrative.")
        restored = NarrativeOutput.model_validate_json(n.model_dump_json())
        assert restored == n
