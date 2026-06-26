"""Unit tests for the deterministic CELLxGENE normalizer.

Offline: organism grounding is driven by a fake resolver, never the live OLS
client, so no network IO occurs.
"""

from __future__ import annotations

from parce.models.graph_schema import EntityType, KnowledgeGraphOutput, MolecularLayer
from parce.models.raw_record import RawRecord
from parce.normalize.cellxgene import CellxgeneNormalizer
from parce.ontology import Facet, ResolvedTerm

_ORGANISMS = {
    "Homo sapiens": ResolvedTerm("NCBITaxon:9606", "Homo sapiens"),
    "Mus musculus": ResolvedTerm("NCBITaxon:10090", "Mus musculus"),
}

# Both CELLxGENE assays in _RECORD are scRNA-seq → transcriptome.
_ASSAY_LAYERS = {
    "EFO:0009922": MolecularLayer.TRANSCRIPTOME,
    "EFO:0008931": MolecularLayer.TRANSCRIPTOME,
}


class _FakeResolver:
    """Deterministic, offline stand-in for the OLS-backed OntologyResolver."""

    def __init__(self) -> None:
        self.layer_calls: list[tuple[str, str | None]] = []

    def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
        if facet is Facet.ORGANISM:
            return _ORGANISMS.get(text)
        return None

    def molecular_layer(self, assay_id: str, *, assay_label: str | None = None) -> MolecularLayer:
        self.layer_calls.append((assay_id, assay_label))
        return _ASSAY_LAYERS.get(assay_id, MolecularLayer.UNKNOWN)


def _normalizer() -> CellxgeneNormalizer:
    return CellxgeneNormalizer(resolver=_FakeResolver())


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
        kg = _normalizer().normalize(_RECORD)

        assert len(kg.studies) == 1
        assert kg.studies[0].study_id == "10.1234/test"
        assert kg.studies[0].title == "Test Study"
        assert kg.studies[0].source == "CELLxGENE"

        assert len(kg.datasets) == 2
        assert kg.datasets[0].dataset_id == "ds-001"
        assert kg.datasets[0].data_uri == "s3://bucket/ds-001.h5ad"
        assert kg.datasets[0].assay == "EFO:0009922"
        assert kg.datasets[1].dataset_id == "ds-002"

    def test_dataset_assay_grounded_to_efo_id(self):
        """Each dataset's assay is the EFO term ID, not the free-text name."""
        kg = _normalizer().normalize(_RECORD)
        assert kg.datasets[0].assay == "EFO:0009922"  # 10x 3' v3
        assert kg.datasets[1].assay == "EFO:0008931"  # Smart-seq2

    def test_dataset_molecular_layer_derived(self):
        """molecular_layer is derived (via the resolver) for each EFO assay."""
        kg = _normalizer().normalize(_RECORD)
        assert kg.datasets[0].molecular_layer is MolecularLayer.TRANSCRIPTOME
        assert kg.datasets[1].molecular_layer is MolecularLayer.TRANSCRIPTOME

    def test_study_assay_is_dominant_and_layer_derived(self):
        """The study's assay is its datasets' most frequent assay, with its layer."""
        kg = _normalizer().normalize(_RECORD)
        # ds-001 (EFO:0009922) and ds-002 (EFO:0008931) tie 1-1; the first seen wins.
        assert kg.studies[0].assay == "EFO:0009922"
        assert kg.studies[0].molecular_layer is MolecularLayer.TRANSCRIPTOME

    def test_layer_derivation_memoised_per_assay(self):
        """Each distinct EFO assay is layer-derived at most once (study reuses it)."""
        resolver = _FakeResolver()
        CellxgeneNormalizer(resolver=resolver).normalize(_RECORD)
        derived_ids = [call[0] for call in resolver.layer_calls]
        assert sorted(set(derived_ids)) == ["EFO:0008931", "EFO:0009922"]
        # No id derived twice despite the study reusing the dominant dataset's assay.
        assert len(derived_ids) == len(set(derived_ids))

    def test_study_source_from_record(self):
        """StudyNode.source is taken from the record, not hardcoded."""
        record = _empty_record()
        record.source = "SomeOtherSource"
        kg = _normalizer().normalize(record)
        assert kg.studies[0].source == "SomeOtherSource"

    def test_cell_type_excluded(self):
        """Cell types in the payload must not produce entities or edges."""
        kg = _normalizer().normalize(_RECORD)

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
        kg = _normalizer().normalize(_RECORD)

        entity_ids = [e.ontology_id for e in kg.biological_entities]
        assert entity_ids.count("UBERON:0000178") == 1

    def test_species_entity_created(self):
        kg = _normalizer().normalize(_RECORD)

        species = [e for e in kg.biological_entities if e.entity_type == EntityType.SPECIES]
        assert len(species) == 1
        assert species[0].ontology_id == "NCBITaxon:9606"
        assert species[0].name == "Homo sapiens"

    def test_no_samples_for_cellxgene(self):
        """Census is dataset-level; no SampleNode records are emitted (yet)."""
        kg = _normalizer().normalize(_RECORD)
        assert kg.samples == []

    def test_extracted_from_edges(self):
        kg = _normalizer().normalize(_RECORD)

        extracted = [e for e in kg.edges if e.relation_type == "EXTRACTED_FROM"]
        assert len(extracted) == 2
        assert {e.source_id for e in extracted} == {"ds-001", "ds-002"}
        assert all(e.target_id == "10.1234/test" for e in extracted)

    def test_has_tissue_edges(self):
        kg = _normalizer().normalize(_RECORD)

        tissue_edges = [e for e in kg.edges if e.relation_type == "HAS_TISSUE"]
        pairs = {(e.source_id, e.target_id) for e in tissue_edges}
        assert ("ds-001", "UBERON:0000178") in pairs
        assert ("ds-002", "UBERON:0000178") in pairs
        assert ("ds-002", "UBERON:0002048") in pairs

    def test_has_condition_edges(self):
        kg = _normalizer().normalize(_RECORD)

        conditions = [e for e in kg.edges if e.relation_type == "HAS_CONDITION"]
        assert any(e.target_id == "PATO:0000461" for e in conditions)

    def test_measured_with_edges(self):
        kg = _normalizer().normalize(_RECORD)

        assay_edges = [e for e in kg.edges if e.relation_type == "MEASURED_WITH"]
        assert any(e.source_id == "ds-001" and e.target_id == "EFO:0009922" for e in assay_edges)
        assert any(e.source_id == "ds-002" and e.target_id == "EFO:0008931" for e in assay_edges)

    def test_studies_edge(self):
        kg = _normalizer().normalize(_RECORD)

        studies = [e for e in kg.edges if e.relation_type == "STUDIES"]
        assert len(studies) == 1
        assert studies[0].source_id == "10.1234/test"
        assert studies[0].target_id == "NCBITaxon:9606"

    def test_empty_datasets(self):
        kg = _normalizer().normalize(_empty_record())

        assert len(kg.studies) == 1
        assert len(kg.datasets) == 0
        assert len(kg.samples) == 0
        assert len(kg.biological_entities) == 0
        assert len(kg.edges) == 0

    def test_roundtrip_json(self):
        kg = _normalizer().normalize(_RECORD)
        restored = KnowledgeGraphOutput.model_validate_json(kg.model_dump_json())
        assert restored == kg

    def test_unresolved_organism_skipped(self):
        """An organism the resolver can't ground yields no species node/edge."""

        class _NoOpResolver:
            def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
                return None

            def molecular_layer(
                self, assay_id: str, *, assay_label: str | None = None
            ) -> MolecularLayer:
                return MolecularLayer.TRANSCRIPTOME

        kg = CellxgeneNormalizer(resolver=_NoOpResolver()).normalize(_RECORD)

        species = [e for e in kg.biological_entities if e.entity_type == EntityType.SPECIES]
        assert species == []
        assert [e for e in kg.edges if e.relation_type == "STUDIES"] == []
        # Non-organism entities are unaffected (they arrive pre-grounded).
        assert any(e.ontology_id == "UBERON:0000178" for e in kg.biological_entities)

    def test_ungrounded_assay_is_unknown_without_resolver_call(self):
        """A dataset with no grounded assay gets assay='unknown', layer=UNKNOWN,
        and the lineage walk is skipped entirely (no EFO id to walk)."""
        record = RawRecord(
            source="CELLxGENE",
            study_id="10.1234/test",
            title="Test Study",
            payload={
                "datasets": [
                    {
                        "dataset_id": "ds-x",
                        "dataset_title": "No assay",
                        "h5ad_uri": "s3://bucket/ds-x.h5ad",
                        "modality": "unknown",
                        "cell_count": 10,
                        "ontology_summary": {"organism": "Homo sapiens", "assays": []},
                    }
                ]
            },
        )
        resolver = _FakeResolver()
        kg = CellxgeneNormalizer(resolver=resolver).normalize(record)

        assert kg.datasets[0].assay == "unknown"
        assert kg.datasets[0].molecular_layer is MolecularLayer.UNKNOWN
        assert kg.studies[0].assay == "unknown"
        assert kg.studies[0].molecular_layer is MolecularLayer.UNKNOWN
        assert resolver.layer_calls == []  # non-EFO assay → no lineage walk
