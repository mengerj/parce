"""Unit tests for the programmatic Knowledge Graph builder."""

from __future__ import annotations

from parce.graph.builder import build_knowledge_graph
from parce.models.graph_schema import EntityType

_PAPER_DATA = {
    "doi": "10.1234/test",
    "title": "Test Study",
    "abstract": "We profiled T cells.",
}

# Note: ``cell_types`` are present in the input but must be ignored by the
# builder (CellType is a data-inferred annotation, intentionally excluded).
# ``blood`` (UBERON:0000178) appears in both datasets to exercise dedup.
_CELLXGENE_DATA = {
    "doi": "10.1234/test",
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
}


class TestBuildKnowledgeGraph:
    def test_basic_structure(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

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

    def test_cell_type_excluded(self):
        """Cell types in the input must not produce entities or edges."""
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

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
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        entity_ids = [e.ontology_id for e in kg.biological_entities]
        assert entity_ids.count("UBERON:0000178") == 1

    def test_species_entity_created(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        species = [e for e in kg.biological_entities if e.entity_type == EntityType.SPECIES]
        assert len(species) == 1
        assert species[0].ontology_id == "NCBITaxon:9606"
        assert species[0].name == "Homo sapiens"

    def test_no_samples_for_cellxgene(self):
        """Census is dataset-level; no SampleNode records are emitted (yet)."""
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)
        assert kg.samples == []

    def test_extracted_from_edges(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        extracted = [e for e in kg.edges if e.relation_type == "EXTRACTED_FROM"]
        assert len(extracted) == 2
        assert {e.source_id for e in extracted} == {"ds-001", "ds-002"}
        assert all(e.target_id == "10.1234/test" for e in extracted)

    def test_has_tissue_edges(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        tissue_edges = [e for e in kg.edges if e.relation_type == "HAS_TISSUE"]
        pairs = {(e.source_id, e.target_id) for e in tissue_edges}
        assert ("ds-001", "UBERON:0000178") in pairs
        assert ("ds-002", "UBERON:0000178") in pairs
        assert ("ds-002", "UBERON:0002048") in pairs

    def test_has_condition_edges(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        conditions = [e for e in kg.edges if e.relation_type == "HAS_CONDITION"]
        assert any(e.target_id == "PATO:0000461" for e in conditions)

    def test_measured_with_edges(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        assay_edges = [e for e in kg.edges if e.relation_type == "MEASURED_WITH"]
        assert any(e.source_id == "ds-001" and e.target_id == "EFO:0009922" for e in assay_edges)
        assert any(e.source_id == "ds-002" and e.target_id == "EFO:0008931" for e in assay_edges)

    def test_studies_edge(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)

        studies = [e for e in kg.edges if e.relation_type == "STUDIES"]
        assert len(studies) == 1
        assert studies[0].source_id == "10.1234/test"
        assert studies[0].target_id == "NCBITaxon:9606"

    def test_empty_datasets(self):
        kg = build_knowledge_graph(_PAPER_DATA, {"doi": "10.1234/test", "datasets": []})

        assert len(kg.studies) == 1
        assert len(kg.datasets) == 0
        assert len(kg.samples) == 0
        assert len(kg.biological_entities) == 0
        assert len(kg.edges) == 0

    def test_roundtrip_json(self):
        kg = build_knowledge_graph(_PAPER_DATA, _CELLXGENE_DATA)
        json_str = kg.model_dump_json()
        from parce.models.graph_schema import KnowledgeGraphOutput

        restored = KnowledgeGraphOutput.model_validate_json(json_str)
        assert restored == kg
