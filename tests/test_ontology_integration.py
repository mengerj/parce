"""Live OLS4 integration tests for the ontology resolver.

These hit the public EBI OLS4 API (no credentials needed) and are excluded from
CI. Run with::

    uv run pytest -m integration tests/test_ontology_integration.py

They validate the network plumbing the unit tests mock: CURIE→IRI construction,
double-encoding, search field parsing, and the ancestor walk. The organism
assertions are exact and reliable. The molecular_layer assertions are exact too:
the anchor keywords in ``parce.ontology.layers`` were validated against this live
EFO branch (the 10x family resolves via the 'transcription profiling' parent;
scRNA/Smart-seq via 'RNA assay'). Extend the cases here as new modalities land.
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
    def test_scrna_seq_is_transcriptome(self, resolver):
        # EFO:0008913 = "single cell RNA sequencing"; reaches the 'RNA assay' anchor.
        layer = resolver.molecular_layer("EFO:0008913", assay_label="single cell RNA sequencing")
        logger.info("Derived molecular_layer for scRNA-seq: %s", layer)
        assert layer is MolecularLayer.TRANSCRIPTOME

    def test_10x_chemistry_is_transcriptome(self, resolver):
        # EFO:0009922 = "10x 3' v3". The 10x family never reaches 'RNA assay'; it
        # must be caught by the 'transcription profiling' parent-process anchor.
        layer = resolver.molecular_layer("EFO:0009922", assay_label="10x 3' v3")
        logger.info("Derived molecular_layer for 10x 3' v3: %s", layer)
        assert layer is MolecularLayer.TRANSCRIPTOME

    def test_atac_seq_is_epigenome(self, resolver):
        # EFO:0007045 = "ATAC-seq"; the epigenome signal lives in the term's own
        # label (its ancestors collapse to a generic 'DNA assay').
        layer = resolver.molecular_layer("EFO:0007045", assay_label="ATAC-seq")
        logger.info("Derived molecular_layer for ATAC-seq: %s", layer)
        assert layer is MolecularLayer.EPIGENOME
