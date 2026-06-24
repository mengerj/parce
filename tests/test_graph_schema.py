"""Unit tests for the canonical Knowledge Graph Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    SampleNode,
    StudyNode,
)


class TestEntityType:
    def test_values(self):
        assert EntityType.DISEASE == "Disease"
        assert EntityType.TISSUE == "Tissue"
        assert EntityType.SPECIES == "Species"
        assert EntityType.PERTURBATION == "Perturbation"
        assert EntityType.ASSAY == "Assay"

    def test_celltype_removed(self):
        """CellType is intentionally absent (data-inferred → leakage)."""
        assert not hasattr(EntityType, "CELL_TYPE")
        with pytest.raises(ValueError):
            EntityType("CellType")

    def test_from_string(self):
        assert EntityType("Disease") is EntityType.DISEASE


class TestStudyNode:
    def test_valid(self):
        study = StudyNode(
            study_id="10.1038/s41586-023-05869-0",
            title="A study",
            source="CELLxGENE",
            modality="scRNA-seq",
        )
        assert study.study_id == "10.1038/s41586-023-05869-0"
        assert study.source == "CELLxGENE"

    def test_no_narrative_field(self):
        """The narrative field was removed from the canonical schema."""
        assert "experimental_narrative" not in StudyNode.model_fields

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            StudyNode(
                study_id="10.1234/test",
                title="T",
                source="CELLxGENE",
                modality="scRNA-seq",
                abstract="leftover",
            )


class TestDatasetNode:
    def test_valid(self):
        ds = DatasetNode(
            dataset_id="abc-123",
            data_uri="s3://cellxgene-data-public/cell-census/h5ads/abc-123.h5ad",
            assay="10x 3' v3",
            cell_count=50000,
        )
        assert ds.cell_count == 50000
        assert ds.assay == "10x 3' v3"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            DatasetNode(dataset_id="x", data_uri="s3://x", assay="m", cell_count=1, oops=True)


class TestSampleNode:
    def test_minimal(self):
        sample = SampleNode(sample_id="GSM0001")
        assert sample.sample_id == "GSM0001"
        assert sample.data_uri is None
        assert sample.organism is None
        assert sample.condition is None
        assert sample.perturbation is None
        assert sample.timepoint is None
        assert sample.subject is None

    def test_full_design_covariates(self):
        sample = SampleNode(
            sample_id="GSM0002",
            data_uri="https://sra/SRR001.fastq",
            organism="Mus musculus",
            condition="stimulated",
            perturbation="Pdcd1 knockout",
            timepoint="day 7",
            subject="donor-3",
        )
        assert sample.perturbation == "Pdcd1 knockout"
        assert sample.timepoint == "day 7"

    def test_no_data_inferred_fields(self):
        """Design covariates only — no cell_type / cluster annotations."""
        assert "cell_type" not in SampleNode.model_fields

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            SampleNode(sample_id="GSM0003", cell_type="CD8+ T cell")


class TestBiologicalEntityNode:
    def test_valid(self):
        entity = BiologicalEntityNode(
            entity_type=EntityType.TISSUE,
            ontology_id="UBERON:0000178",
            name="blood",
        )
        assert entity.entity_type == EntityType.TISSUE

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

    def test_celltype_rejected(self):
        with pytest.raises(ValidationError):
            BiologicalEntityNode(entity_type="CellType", ontology_id="CL:0000084", name="T cell")

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
        assert kg.studies == []
        assert kg.samples == []
        assert kg.edges == []

    def test_roundtrip_json(self):
        kg = KnowledgeGraphOutput(
            studies=[
                StudyNode(
                    study_id="10.1234/test",
                    title="Test",
                    source="CELLxGENE",
                    modality="scRNA-seq",
                )
            ],
            datasets=[
                DatasetNode(
                    dataset_id="ds-1",
                    data_uri="s3://bucket/ds-1.h5ad",
                    assay="10x 3' v3",
                    cell_count=1000,
                )
            ],
            samples=[
                SampleNode(
                    sample_id="GSM1",
                    organism="Homo sapiens",
                    condition="control",
                )
            ],
            biological_entities=[
                BiologicalEntityNode(
                    entity_type=EntityType.TISSUE,
                    ontology_id="UBERON:0000178",
                    name="blood",
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
