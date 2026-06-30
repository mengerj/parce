"""Unit tests for the cross-source KG merge (``parce.graph.merge``).

Fully offline. The cross-source case runs the *real* CELLxGENE and GEO normalizers
(with fake resolvers/extractors — no network, no Azure) so the test proves that
genuine per-source output links through shared ontology entities once merged. The
mechanical merge/provenance behaviours are pinned with small hand-built graphs.
"""

from __future__ import annotations

import logging

from parce.graph import (
    EntityProvenance,
    cross_source_entities,
    entity_provenance,
    merge_subgraphs,
)
from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    MolecularLayer,
    SampleNode,
    StudyNode,
)
from parce.models.raw_record import RawRecord
from parce.normalize.cellxgene import CellxgeneNormalizer
from parce.normalize.geo import GeoExtraction, GeoNormalizer, SampleExtraction
from parce.ontology import Facet, ResolvedTerm

# --------------------------------------------------------------------------- #
# Offline fakes + records for the two real source normalizers. The two studies
# deliberately share lung (UBERON:0002048) and human (NCBITaxon:9606) so a
# cross-source link must emerge; everything else is source-private.
# --------------------------------------------------------------------------- #


class _CxgResolver:
    def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
        if facet is Facet.ORGANISM and text == "Homo sapiens":
            return ResolvedTerm("NCBITaxon:9606", "Homo sapiens")
        return None

    def molecular_layer(self, assay_id: str, *, assay_label: str | None = None) -> MolecularLayer:
        return (
            MolecularLayer.TRANSCRIPTOME if assay_id.startswith("EFO:") else MolecularLayer.UNKNOWN
        )


_CXG_RECORD = RawRecord(
    source="CELLxGENE",
    study_id="10.1234/cxg",
    title="Single-cell lung atlas",
    payload={
        "datasets": [
            {
                "dataset_id": "cxg-ds-1",
                "h5ad_uri": "s3://bucket/cxg-ds-1.h5ad",
                "modality": "10x 3' v3",
                "cell_count": 1000,
                "ontology_summary": {
                    "organism": "Homo sapiens",
                    "modality": "10x 3' v3",
                    "tissues": [
                        {"name": "lung", "ontology_id": "UBERON:0002048"},
                        {"name": "blood", "ontology_id": "UBERON:0000178"},
                    ],
                    "diseases": [],
                    "assays": [{"name": "10x 3' v3", "ontology_id": "EFO:0009922"}],
                },
            }
        ]
    },
)


_GEO_TERMS = {
    (Facet.ORGANISM, "Homo sapiens"): ResolvedTerm("NCBITaxon:9606", "Homo sapiens"),
    (Facet.ASSAY, "RNA-seq"): ResolvedTerm("EFO:0008896", "RNA-seq"),
    (Facet.TISSUE, "lung"): ResolvedTerm("UBERON:0002048", "lung"),
    (Facet.DISEASE, "lung adenocarcinoma"): ResolvedTerm("MONDO:0005061", "lung adenocarcinoma"),
}


class _GeoResolver:
    def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
        return _GEO_TERMS.get((facet, text))

    def molecular_layer(self, assay_id: str, *, assay_label: str | None = None) -> MolecularLayer:
        return (
            MolecularLayer.TRANSCRIPTOME if assay_id.startswith("EFO:") else MolecularLayer.UNKNOWN
        )


class _StaticExtractor:
    def __init__(self, extraction: GeoExtraction) -> None:
        self._extraction = extraction

    def extract(self, instructions, content, response_model):  # type: ignore[no-untyped-def]
        return self._extraction


_GEO_RECORD = RawRecord(
    source="GEO",
    study_id="GSE99999",
    title="Lung adenocarcinoma bulk RNA-seq",
    payload={
        "series": {
            "type": ["Expression profiling by high throughput sequencing"],
            "summary": ["Bulk RNA-seq of lung tumour and normal tissue."],
            "overall_design": "tumour vs normal",
        },
        "samples": [
            {
                "sample_id": "GSM1",
                "title": "tumour",
                "source_name": "lung",
                "organism": "Homo sapiens",
                "characteristics": ["tissue: lung"],
                "supplementary_file": "ftp://host/GSM1.bam",
            },
            {
                "sample_id": "GSM2",
                "title": "normal",
                "source_name": "lung",
                "organism": "Homo sapiens",
                "characteristics": ["tissue: lung"],
                "supplementary_file": "ftp://host/GSM2.bam",
            },
        ],
        "truncated": False,
    },
)

_GEO_EXTRACTION = GeoExtraction(
    assay="RNA-seq",
    tissue="lung",
    disease="lung adenocarcinoma",
    samples=[
        SampleExtraction(sample_id="GSM1", condition="tumour"),
        SampleExtraction(sample_id="GSM2", condition="normal"),
    ],
)


def _cxg_subgraph() -> KnowledgeGraphOutput:
    return CellxgeneNormalizer(resolver=_CxgResolver()).normalize(_CXG_RECORD)


def _geo_subgraph() -> KnowledgeGraphOutput:
    return GeoNormalizer(_StaticExtractor(_GEO_EXTRACTION), resolver=_GeoResolver()).normalize(
        _GEO_RECORD
    )


# --------------------------------------------------------------------------- #
# Cross-source merge of real normalizer output.
# --------------------------------------------------------------------------- #


class TestCrossSourceMerge:
    def test_all_study_dataset_sample_nodes_kept(self):
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        assert {s.study_id for s in merged.studies} == {"10.1234/cxg", "GSE99999"}
        assert {d.dataset_id for d in merged.datasets} == {"cxg-ds-1"}  # GEO has none
        assert {s.sample_id for s in merged.samples} == {"GSM1", "GSM2"}  # CELLxGENE has none

    def test_shared_entity_deduped_to_single_node(self):
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        lung = [e for e in merged.biological_entities if e.ontology_id == "UBERON:0002048"]
        human = [e for e in merged.biological_entities if e.ontology_id == "NCBITaxon:9606"]
        assert len(lung) == 1  # touched by both sources, one node
        assert len(human) == 1

    def test_source_private_entities_survive(self):
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        ids = {e.ontology_id for e in merged.biological_entities}
        assert "UBERON:0000178" in ids  # blood, CELLxGENE-only
        assert "MONDO:0005061" in ids  # disease, GEO-only
        assert "EFO:0009922" in ids and "EFO:0008896" in ids  # distinct assays

    def test_shared_entity_links_both_sources(self):
        """The headline guarantee: a shared entity is touched by both sources."""
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        prov = entity_provenance(merged)
        lung = prov["UBERON:0002048"]
        assert lung.sources == frozenset({"CELLxGENE", "GEO"})
        assert lung.studies == frozenset({"10.1234/cxg", "GSE99999"})

    def test_cross_source_entities_are_exactly_the_shared_ones(self):
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        assert set(cross_source_entities(merged)) == {"UBERON:0002048", "NCBITaxon:9606"}

    def test_private_entity_is_single_source(self):
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        blood = entity_provenance(merged)["UBERON:0000178"]
        assert blood.sources == frozenset({"CELLxGENE"})
        assert "UBERON:0000178" not in cross_source_entities(merged)

    def test_edges_into_shared_entity_preserved_from_both_sources(self):
        """Entity nodes dedup, but the edges that touch them are not merged away."""
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        sources_into_lung = {
            e.source_id
            for e in merged.edges
            if e.target_id == "UBERON:0002048" and e.relation_type == "HAS_TISSUE"
        }
        assert sources_into_lung == {"cxg-ds-1", "GSE99999"}


# --------------------------------------------------------------------------- #
# Mechanical merge behaviour (hand-built graphs).
# --------------------------------------------------------------------------- #


def _entity(ont_id: str, name: str, etype: EntityType = EntityType.TISSUE) -> BiologicalEntityNode:
    return BiologicalEntityNode(entity_type=etype, ontology_id=ont_id, name=name)


def _study(study_id: str, source: str) -> StudyNode:
    return StudyNode(study_id=study_id, title=study_id, source=source, assay="unknown")


class TestMergeMechanics:
    def test_empty_input(self):
        merged = merge_subgraphs([])
        assert merged == KnowledgeGraphOutput()

    def test_single_subgraph_preserved(self):
        sg = _cxg_subgraph()
        merged = merge_subgraphs([sg])
        assert len(merged.studies) == len(sg.studies)
        assert len(merged.datasets) == len(sg.datasets)
        assert len(merged.biological_entities) == len(sg.biological_entities)
        assert len(merged.edges) == len(sg.edges)

    def test_idempotent_on_repeated_subgraph(self):
        sg = _cxg_subgraph()
        once = merge_subgraphs([sg])
        twice = merge_subgraphs([sg, sg])
        assert len(twice.studies) == len(once.studies)
        assert len(twice.datasets) == len(once.datasets)
        assert len(twice.biological_entities) == len(once.biological_entities)
        assert len(twice.edges) == len(once.edges)

    def test_entity_dedup_by_ontology_id(self):
        a = KnowledgeGraphOutput(biological_entities=[_entity("UBERON:1", "lung")])
        b = KnowledgeGraphOutput(biological_entities=[_entity("UBERON:1", "lung")])
        merged = merge_subgraphs([a, b])
        assert len(merged.biological_entities) == 1

    def test_entity_name_backfilled_when_first_unknown(self):
        a = KnowledgeGraphOutput(biological_entities=[_entity("UBERON:1", "unknown")])
        b = KnowledgeGraphOutput(biological_entities=[_entity("UBERON:1", "lung")])
        merged = merge_subgraphs([a, b])
        assert merged.biological_entities[0].name == "lung"

    def test_first_real_name_wins_over_later(self):
        a = KnowledgeGraphOutput(biological_entities=[_entity("UBERON:1", "lung")])
        b = KnowledgeGraphOutput(biological_entities=[_entity("UBERON:1", "pulmonary tissue")])
        merged = merge_subgraphs([a, b])
        assert merged.biological_entities[0].name == "lung"

    def test_entity_type_conflict_keeps_first_and_warns(self, caplog):
        a = KnowledgeGraphOutput(biological_entities=[_entity("X:1", "x", EntityType.TISSUE)])
        b = KnowledgeGraphOutput(biological_entities=[_entity("X:1", "x", EntityType.DISEASE)])
        with caplog.at_level(logging.WARNING, logger="parce.graph.merge"):
            merged = merge_subgraphs([a, b])
        assert merged.biological_entities[0].entity_type is EntityType.TISSUE
        assert "conflicting" in caplog.text.lower() or "both" in caplog.text.lower()

    def test_distinct_edges_to_same_target_all_kept(self):
        a = KnowledgeGraphOutput(
            edges=[GraphEdge(source_id="d1", target_id="U:1", relation_type="HAS_TISSUE")]
        )
        b = KnowledgeGraphOutput(
            edges=[GraphEdge(source_id="d2", target_id="U:1", relation_type="HAS_TISSUE")]
        )
        merged = merge_subgraphs([a, b])
        assert len(merged.edges) == 2

    def test_exact_duplicate_edges_collapse(self):
        edge = GraphEdge(source_id="d1", target_id="U:1", relation_type="HAS_TISSUE")
        a = KnowledgeGraphOutput(edges=[edge])
        b = KnowledgeGraphOutput(edges=[edge.model_copy()])
        merged = merge_subgraphs([a, b])
        assert len(merged.edges) == 1

    def test_returns_roundtrippable_knowledge_graph(self):
        merged = merge_subgraphs([_cxg_subgraph(), _geo_subgraph()])
        assert isinstance(merged, KnowledgeGraphOutput)
        restored = KnowledgeGraphOutput.model_validate_json(merged.model_dump_json())
        assert restored == merged


# --------------------------------------------------------------------------- #
# Provenance derivation in isolation (owner-tracing across node kinds).
# --------------------------------------------------------------------------- #


class TestEntityProvenance:
    def test_dataset_edge_traced_to_owning_study(self):
        """A CELLxGENE-style dataset-level edge is attributed to its study."""
        graph = KnowledgeGraphOutput(
            studies=[_study("STUDY_A", "CELLxGENE")],
            datasets=[
                DatasetNode(dataset_id="ds1", data_uri="s3://x", assay="EFO:1", cell_count=1)
            ],
            biological_entities=[_entity("UBERON:1", "lung")],
            edges=[
                GraphEdge(source_id="ds1", target_id="STUDY_A", relation_type="EXTRACTED_FROM"),
                GraphEdge(source_id="ds1", target_id="UBERON:1", relation_type="HAS_TISSUE"),
            ],
        )
        prov = entity_provenance(graph)["UBERON:1"]
        assert prov == EntityProvenance(
            "UBERON:1", frozenset({"STUDY_A"}), frozenset({"CELLxGENE"})
        )

    def test_study_and_sample_edges_traced(self):
        """GEO-style study-level edge and a sample-owned edge both attribute correctly."""
        graph = KnowledgeGraphOutput(
            studies=[_study("GSE1", "GEO")],
            samples=[SampleNode(sample_id="GSM1")],
            biological_entities=[
                _entity("UBERON:1", "lung"),
                _entity("NCBITaxon:9606", "human", EntityType.SPECIES),
            ],
            edges=[
                GraphEdge(source_id="GSE1", target_id="GSM1", relation_type="HAS_SAMPLE"),
                GraphEdge(source_id="GSE1", target_id="UBERON:1", relation_type="HAS_TISSUE"),
                GraphEdge(source_id="GSE1", target_id="NCBITaxon:9606", relation_type="STUDIES"),
            ],
        )
        prov = entity_provenance(graph)
        assert prov["UBERON:1"].studies == frozenset({"GSE1"})
        assert prov["NCBITaxon:9606"].sources == frozenset({"GEO"})

    def test_untouched_entity_has_empty_provenance(self):
        graph = KnowledgeGraphOutput(
            studies=[_study("S", "GEO")],
            biological_entities=[_entity("UBERON:9", "orphan")],
        )
        prov = entity_provenance(graph)["UBERON:9"]
        assert prov.studies == frozenset() and prov.sources == frozenset()
