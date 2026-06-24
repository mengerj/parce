"""Unit tests for the deterministic CELLxGENE normalizer."""

from __future__ import annotations

from parce.models.graph_schema import EntityType, KnowledgeGraphOutput
from parce.models.raw_record import RawRecord
from parce.normalize.cellxgene import CellxgeneNormalizer

# ``cell_types`` are intentionally present in the payload to prove the normalizer
# ignores them (CellType is a data-inferred annotation, deliberately excluded).
# ``blood`` (UBERON:0000178) appears in both datasets to exercise dedup.
_RECORD = RawRecord(
    source="CELLxGENE",
    study_id="10.1234/test",
    title="Test Study",
    payload={
        "datasets": [
            {
                "dataset_id": "ds-001",
                "dataset_title": "Dataset One",
                "h5ad_uri": "s3://bucket/ds-001.h5ad",
                "modality": "10x 3' v3",
                "cell_count": 5000,
                "ontology_summary": {
                    "organism": "Homo sapiens",
                    "modality": "10x 3' v3",
                    "cell_types": [
                        {"name": "T cell", "ontology_id": "CL:0000084"},
                        {"name": "B cell", "ontology_id": "CL:0000236"},
                    ],
                    "tissues": [
                        {"name": "blood", "ontology_id": "UBERON:0000178"},
                    ],
                    "diseases": [
                        {"name": "normal", "ontology_id": "PATO:0000461"},
                    ],
                    "assays": [
                        {"name": "10x 3' v3", "ontology_id": "EFO:0009922"},
                    ],
                },
            },
            {
                "dataset_id": "ds-002",
                "dataset_title": "Dataset Two",
                "h5ad_uri": "s3://bucket/ds-002.h5ad",
                "modality": "Smart-seq2",
                "cell_count": 1000,
                "ontology_summary": {
                    "organism": "Homo sapiens",
                    "modality": "Smart-seq2",
                    "cell_types": [
                        {"name": "T cell", "ontology_id": "CL:0000084"},
                    ],
                    "tissues": [
                        {"name": "blood", "ontology_id": "UBERON:0000178"},
                        {"name": "lung", "ontology_id": "UBERON:0002048"},
                    ],
                    "diseases": [],
                    "assays": [
                        {"name": "Smart-seq2", "ontology_id": "EFO:0008931"},
                    ],
                },
            },
        ],
    },
)


def _empty_record() -> RawRecord:
    return RawRecord(
        source="CELLxGENE",
        study_id="10.1234/test",
        title="Test Study",
        payload={"datasets": []},
    )


class TestCellxgeneNormalizer:
    def test_basic_structure(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        assert len(kg.studies) == 1
        assert kg.studies[0].study_id == "10.1234/test"
        assert kg.studies[0].title == "Test Study"
        assert kg.studies[0].source == "CELLxGENE"
        assert kg.studies[0].modality == "scRNA-seq"

        assert len(kg.datasets) == 2
        assert kg.datasets[0].dataset_id == "ds-001"
        assert kg.datasets[0].data_uri == "s3://bucket/ds-001.h5ad"
        assert kg.datasets[0].assay == "10x 3' v3"
        assert kg.datasets[1].dataset_id == "ds-002"

    def test_study_source_from_record(self):
        """StudyNode.source is taken from the record, not hardcoded."""
        record = _empty_record()
        record.source = "SomeOtherSource"
        kg = CellxgeneNormalizer().normalize(record)
        assert kg.studies[0].source == "SomeOtherSource"

    def test_cell_type_excluded(self):
        """Cell types in the payload must not produce entities or edges."""
        kg = CellxgeneNormalizer().normalize(_RECORD)

        names = {e.name for e in kg.biological_entities}
        assert "T cell" not in names
        assert "B cell" not in names

        ontology_ids = {e.ontology_id for e in kg.biological_entities}
        assert "CL:0000084" not in ontology_ids
        assert "CL:0000236" not in ontology_ids

        edge_targets = {e.target_id for e in kg.edges}
        assert "CL:0000084" not in edge_targets

    def test_tissue_entity_deduplication(self):
        """blood (UBERON:0000178) appears in both datasets but is one entity."""
        kg = CellxgeneNormalizer().normalize(_RECORD)

        entity_ids = [e.ontology_id for e in kg.biological_entities]
        assert entity_ids.count("UBERON:0000178") == 1

    def test_species_entity_created(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        species = [e for e in kg.biological_entities if e.entity_type == EntityType.SPECIES]
        assert len(species) == 1
        assert species[0].ontology_id == "NCBITaxon:9606"
        assert species[0].name == "Homo sapiens"

    def test_no_samples_for_cellxgene(self):
        """Census is dataset-level; no SampleNode records are emitted (yet)."""
        kg = CellxgeneNormalizer().normalize(_RECORD)
        assert kg.samples == []

    def test_extracted_from_edges(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        extracted = [e for e in kg.edges if e.relation_type == "EXTRACTED_FROM"]
        assert len(extracted) == 2
        assert {e.source_id for e in extracted} == {"ds-001", "ds-002"}
        assert all(e.target_id == "10.1234/test" for e in extracted)

    def test_has_tissue_edges(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        tissue_edges = [e for e in kg.edges if e.relation_type == "HAS_TISSUE"]
        pairs = {(e.source_id, e.target_id) for e in tissue_edges}
        assert ("ds-001", "UBERON:0000178") in pairs
        assert ("ds-002", "UBERON:0000178") in pairs
        assert ("ds-002", "UBERON:0002048") in pairs

    def test_has_condition_edges(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        conditions = [e for e in kg.edges if e.relation_type == "HAS_CONDITION"]
        assert any(e.target_id == "PATO:0000461" for e in conditions)

    def test_measured_with_edges(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        assay_edges = [e for e in kg.edges if e.relation_type == "MEASURED_WITH"]
        assert any(e.source_id == "ds-001" and e.target_id == "EFO:0009922" for e in assay_edges)
        assert any(e.source_id == "ds-002" and e.target_id == "EFO:0008931" for e in assay_edges)

    def test_studies_edge(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)

        studies = [e for e in kg.edges if e.relation_type == "STUDIES"]
        assert len(studies) == 1
        assert studies[0].source_id == "10.1234/test"
        assert studies[0].target_id == "NCBITaxon:9606"

    def test_empty_datasets(self):
        kg = CellxgeneNormalizer().normalize(_empty_record())

        assert len(kg.studies) == 1
        assert len(kg.datasets) == 0
        assert len(kg.samples) == 0
        assert len(kg.biological_entities) == 0
        assert len(kg.edges) == 0

    def test_roundtrip_json(self):
        kg = CellxgeneNormalizer().normalize(_RECORD)
        restored = KnowledgeGraphOutput.model_validate_json(kg.model_dump_json())
        assert restored == kg
