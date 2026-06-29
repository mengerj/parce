"""Unit tests for the agent-backed GEO normalizer.

Offline: the LLM is a deterministic fake :class:`StructuredExtractor` returning a
canned :class:`GeoExtraction`, and ontology grounding is a fake resolver. No
network, no Azure.
"""

from __future__ import annotations

import pytest

from parce.agent.base import SchemaT, StructuredExtractor
from parce.models.graph_schema import EntityType, KnowledgeGraphOutput, MolecularLayer
from parce.models.raw_record import RawRecord
from parce.normalize.base import Normalizer
from parce.normalize.geo import GeoExtraction, GeoNormalizer, SampleExtraction
from parce.ontology import Facet, ResolvedTerm

# Grounding table the fake resolver uses (organism/assay/tissue/disease).
_TERMS = {
    (Facet.ORGANISM, "Homo sapiens"): ResolvedTerm("NCBITaxon:9606", "Homo sapiens"),
    (Facet.ASSAY, "microarray"): ResolvedTerm("EFO:0002772", "microarray"),
    (Facet.TISSUE, "lung"): ResolvedTerm("UBERON:0002048", "lung"),
    (Facet.DISEASE, "lung adenocarcinoma"): ResolvedTerm("MONDO:0005061", "lung adenocarcinoma"),
}


class _FakeResolver:
    """Offline OntologyService stand-in."""

    def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
        return _TERMS.get((facet, text))

    def molecular_layer(self, assay_id: str, *, assay_label: str | None = None) -> MolecularLayer:
        return (
            MolecularLayer.TRANSCRIPTOME if assay_id.startswith("EFO:") else MolecularLayer.UNKNOWN
        )


class _FakeExtractor:
    """Returns a preset GeoExtraction, recording the call for assertions."""

    def __init__(self, extraction: GeoExtraction) -> None:
        self._extraction = extraction
        self.calls: list[tuple[str, str]] = []

    def extract(self, instructions: str, content: str, response_model: type[SchemaT]) -> SchemaT:
        self.calls.append((instructions, content))
        assert response_model is GeoExtraction
        return self._extraction  # type: ignore[return-value]


class _RaisingExtractor:
    def extract(self, instructions: str, content: str, response_model: type[SchemaT]) -> SchemaT:
        raise RuntimeError("LLM unavailable")


def _record() -> RawRecord:
    return RawRecord(
        source="GEO",
        study_id="GSE99999",
        title="Smoking and lung adenocarcinoma",
        payload={
            "series": {
                "type": ["Expression profiling by array"],
                "summary": ["We profiled tumor and normal lung tissue."],
                "overall_design": "2 tumor and 2 normal.",
            },
            "samples": [
                {
                    "sample_id": "GSM000001",
                    "title": "Lung Tumor A",
                    "source_name": "Adenocarcinoma of the Lung",
                    "organism": "Homo sapiens",
                    "characteristics": ["gender: Male", "tissue: tumor"],
                    "supplementary_file": "ftp://host/GSM000001.CEL.gz",
                },
                {
                    "sample_id": "GSM000002",
                    "title": "Lung Normal A",
                    "source_name": "Noninvolved Lung",
                    "organism": "Homo sapiens",
                    "characteristics": ["gender: Female", "tissue: normal"],
                    "supplementary_file": "ftp://host/GSM000002.CEL.gz",
                },
            ],
            "truncated": False,
        },
    )


def _extraction() -> GeoExtraction:
    return GeoExtraction(
        assay="microarray",
        tissue="lung",
        disease="lung adenocarcinoma",
        samples=[
            SampleExtraction(sample_id="GSM000001", condition="tumor", subject="P1"),
            SampleExtraction(sample_id="GSM000002", condition="normal", subject="P1"),
        ],
    )


def _normalizer(extraction: GeoExtraction | None = None) -> GeoNormalizer:
    return GeoNormalizer(_FakeExtractor(extraction or _extraction()), resolver=_FakeResolver())


class TestGeoNormalizer:
    def test_study_node(self):
        kg = _normalizer().normalize(_record())
        assert len(kg.studies) == 1
        study = kg.studies[0]
        assert study.study_id == "GSE99999"
        assert study.source == "GEO"
        assert study.assay == "EFO:0002772"
        assert study.molecular_layer is MolecularLayer.TRANSCRIPTOME

    def test_no_dataset_node_for_geo(self):
        """GEO has no distinct dataset artifact — the series is the study."""
        assert _normalizer().normalize(_record()).datasets == []

    def test_one_sample_node_per_record_sample(self):
        kg = _normalizer().normalize(_record())
        assert [s.sample_id for s in kg.samples] == ["GSM000001", "GSM000002"]

    def test_sample_covariates_from_llm_structured_from_record(self):
        kg = _normalizer().normalize(_record())
        s1 = kg.samples[0]
        # Design covariates come from the LLM extraction.
        assert s1.condition == "tumor"
        assert s1.subject == "P1"
        # organism + data_uri are read deterministically from the record, not the LLM.
        assert s1.organism == "Homo sapiens"
        assert s1.data_uri == "ftp://host/GSM000001.CEL.gz"

    def test_has_sample_edges(self):
        kg = _normalizer().normalize(_record())
        has_sample = [e for e in kg.edges if e.relation_type == "HAS_SAMPLE"]
        assert {(e.source_id, e.target_id) for e in has_sample} == {
            ("GSE99999", "GSM000001"),
            ("GSE99999", "GSM000002"),
        }

    def test_study_level_entities_grounded(self):
        kg = _normalizer().normalize(_record())
        by_type = {e.entity_type: e for e in kg.biological_entities}
        assert by_type[EntityType.ASSAY].ontology_id == "EFO:0002772"
        assert by_type[EntityType.TISSUE].ontology_id == "UBERON:0002048"
        assert by_type[EntityType.DISEASE].ontology_id == "MONDO:0005061"
        assert by_type[EntityType.SPECIES].ontology_id == "NCBITaxon:9606"

    def test_design_context_edges_from_study(self):
        kg = _normalizer().normalize(_record())
        rels = {(e.relation_type, e.target_id) for e in kg.edges if e.source_id == "GSE99999"}
        assert ("MEASURED_WITH", "EFO:0002772") in rels
        assert ("HAS_TISSUE", "UBERON:0002048") in rels
        assert ("HAS_CONDITION", "MONDO:0005061") in rels
        assert ("STUDIES", "NCBITaxon:9606") in rels

    def test_no_cell_type_entities(self):
        """Even if covariates mention cells, no CL entity is ever produced."""
        kg = _normalizer().normalize(_record())
        assert all(not e.ontology_id.startswith("CL:") for e in kg.biological_entities)

    def test_unresolved_facets_skipped(self):
        """Facets the resolver can't ground produce no entity; assay falls to unknown."""
        extraction = GeoExtraction(assay="hand-wavy assay", tissue=None, disease=None, samples=[])
        kg = _normalizer(extraction).normalize(_record())
        assert kg.studies[0].assay == "unknown"
        assert kg.studies[0].molecular_layer is MolecularLayer.UNKNOWN
        # Species still grounds from the record's structured organism field.
        assert any(e.entity_type == EntityType.SPECIES for e in kg.biological_entities)
        assert not any(e.entity_type == EntityType.ASSAY for e in kg.biological_entities)

    def test_extraction_failure_degrades_gracefully(self):
        """An LLM error yields samples (from the record) but no extracted covariates."""
        normalizer = GeoNormalizer(_RaisingExtractor(), resolver=_FakeResolver())
        kg = normalizer.normalize(_record())
        assert len(kg.samples) == 2
        assert all(s.condition is None for s in kg.samples)
        assert kg.studies[0].assay == "unknown"
        # Organism is structured → species still resolves despite the LLM failure.
        assert any(e.entity_type == EntityType.SPECIES for e in kg.biological_entities)

    def test_agent_receives_characteristics_in_prompt(self):
        extractor = _FakeExtractor(_extraction())
        GeoNormalizer(extractor, resolver=_FakeResolver()).normalize(_record())
        _, content = extractor.calls[0]
        assert "GSM000001" in content
        assert "gender: Male" in content

    def test_roundtrip_json(self):
        kg = _normalizer().normalize(_record())
        restored = KnowledgeGraphOutput.model_validate_json(kg.model_dump_json())
        assert restored == kg


class TestProtocolConformance:
    def test_normalizer_satisfies_protocol(self):
        assert isinstance(GeoNormalizer(_FakeExtractor(_extraction())), Normalizer)

    def test_fake_extractor_satisfies_structured_extractor(self):
        assert isinstance(_FakeExtractor(_extraction()), StructuredExtractor)


# -- LLM ontology fallback factory (uses a fake extractor, no Azure) ----------


class _FallbackExtractor:
    """Returns a preset object for the fallback's private _FallbackTerm schema."""

    def __init__(self, ontology_id: str | None, name: str | None) -> None:
        self._ontology_id = ontology_id
        self._name = name

    def extract(self, instructions: str, content: str, response_model: type[SchemaT]) -> SchemaT:
        return response_model(ontology_id=self._ontology_id, name=self._name)  # type: ignore[call-arg]


class TestOntologyFallbackFactory:
    def test_accepts_correct_prefix(self):
        from parce.agent.extraction import make_ontology_fallback

        fallback = make_ontology_fallback(_FallbackExtractor("UBERON:0002048", "lung"))
        term = fallback("pulmonary tissue", Facet.TISSUE)
        assert term == ResolvedTerm("UBERON:0002048", "lung")

    def test_rejects_wrong_prefix(self):
        from parce.agent.extraction import make_ontology_fallback

        # A MONDO id returned for a TISSUE facet (expects UBERON) is dropped.
        fallback = make_ontology_fallback(_FallbackExtractor("MONDO:0005061", "x"))
        assert fallback("pulmonary tissue", Facet.TISSUE) is None

    def test_rejects_null(self):
        from parce.agent.extraction import make_ontology_fallback

        fallback = make_ontology_fallback(_FallbackExtractor(None, None))
        assert fallback("???", Facet.TISSUE) is None

    def test_extractor_error_returns_none(self):
        from parce.agent.extraction import make_ontology_fallback

        fallback = make_ontology_fallback(_RaisingExtractor())
        assert fallback("lung", Facet.TISSUE) is None


@pytest.mark.parametrize(
    "field",
    ["condition", "perturbation", "timepoint", "subject"],
)
def test_sample_extraction_design_only(field):
    """The extraction schema exposes only design covariates (no cell-type field)."""
    assert field in SampleExtraction.model_fields
    assert "cell_type" not in SampleExtraction.model_fields
    assert "cell_type" not in GeoExtraction.model_fields
