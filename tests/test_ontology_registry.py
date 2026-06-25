"""Unit tests for the facet → ontology registry (pure data, no IO)."""

from __future__ import annotations

from parce.ontology.registry import (
    CHEBI,
    EDAM,
    EFO,
    FACET_ONTOLOGY,
    MONDO,
    NCBITAXON,
    OBI,
    PSI_MS,
    UBERON,
    Facet,
)


class TestRegistry:
    def test_every_facet_is_bound(self):
        assert set(FACET_ONTOLOGY) == set(Facet)

    def test_primary_bindings(self):
        primaries = {facet: binding.primary for facet, binding in FACET_ONTOLOGY.items()}
        assert primaries[Facet.ASSAY] is EFO
        assert primaries[Facet.TISSUE] is UBERON
        assert primaries[Facet.DISEASE] is MONDO
        assert primaries[Facet.ORGANISM] is NCBITAXON
        assert primaries[Facet.PERTURBATION] is CHEBI
        assert primaries[Facet.DATA_FORMAT] is EDAM

    def test_all_seven_pinned_ontologies_present(self):
        """The seven ontologies named in ARCHITECTURE §5 all appear."""
        used = set()
        for binding in FACET_ONTOLOGY.values():
            used.update(binding.ontologies())
        assert {EFO, OBI, PSI_MS, UBERON, MONDO, NCBITAXON, CHEBI, EDAM} <= used

    def test_assay_falls_back_to_obi_then_psi_ms(self):
        binding = FACET_ONTOLOGY[Facet.ASSAY]
        assert binding.ontologies() == (EFO, OBI, PSI_MS)

    def test_organism_has_no_fallback(self):
        assert FACET_ONTOLOGY[Facet.ORGANISM].ontologies() == (NCBITAXON,)

    def test_curie_prefixes(self):
        assert NCBITAXON.prefix == "NCBITaxon"
        assert EFO.prefix == "EFO"
        assert UBERON.prefix == "UBERON"

    def test_ols_slugs_are_lowercase(self):
        for binding in FACET_ONTOLOGY.values():
            for onto in binding.ontologies():
                assert onto.ols_id == onto.ols_id.lower()
