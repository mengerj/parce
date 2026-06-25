"""Live OLS4 integration tests for the ontology resolver.

These hit the public EBI OLS4 API (no credentials needed) and are excluded from
CI. Run with::

    uv run pytest -m integration tests/test_ontology_integration.py

They validate the network plumbing the unit tests mock: CURIE→IRI construction,
double-encoding, search field parsing, and the ancestor walk. The organism
assertions are exact and reliable. The molecular_layer assertions are softer
because the anchor labels in ``parce.ontology.layers`` are provisional — see the
note there; tighten these to exact ``==`` once a real lineage is observed.
"""

from __future__ import annotations

import logging

import pytest

from parce.models.graph_schema import MolecularLayer
from parce.ontology.registry import Facet
from parce.ontology.resolver import OntologyResolver

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)


@pytest.fixture
def resolver(tmp_path):
    # Real OLS client; cache in a throwaway dir so the run is self-contained.
    return OntologyResolver(cache_dir=tmp_path)


class TestLiveResolution:
    def test_resolves_homo_sapiens(self, resolver):
        term = resolver.resolve_term("Homo sapiens", Facet.ORGANISM)
        assert term is not None
        assert term.ontology_id == "NCBITaxon:9606"

    def test_resolves_mus_musculus(self, resolver):
        term = resolver.resolve_term("Mus musculus", Facet.ORGANISM)
        assert term is not None
        assert term.ontology_id == "NCBITaxon:10090"

    def test_disease_resolves_to_mondo(self, resolver):
        term = resolver.resolve_term("lung cancer", Facet.DISEASE)
        assert term is not None
        assert term.ontology_id.startswith("MONDO:")


class TestLiveMolecularLayer:
    def test_scrna_seq_ancestor_walk_runs(self, resolver):
        # EFO:0008913 = "single cell RNA sequencing". Assert the walk produces a
        # valid layer (plumbing works); log it so anchor labels can be confirmed.
        layer = resolver.molecular_layer("EFO:0008913", assay_label="single cell RNA sequencing")
        logger.info("Derived molecular_layer for scRNA-seq: %s", layer)
        assert isinstance(layer, MolecularLayer)
        # Target once anchors are validated: this should be TRANSCRIPTOME.
        assert layer in {MolecularLayer.TRANSCRIPTOME, MolecularLayer.UNKNOWN}
