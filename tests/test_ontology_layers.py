"""Unit tests for the molecular_layer derivation (pure function, no IO)."""

from __future__ import annotations

from parce.models.graph_schema import MolecularLayer
from parce.ontology.layers import derive_molecular_layer


class TestDeriveMolecularLayer:
    def test_transcriptome(self):
        labels = ["single-cell RNA sequencing", "RNA assay", "assay by molecule"]
        assert derive_molecular_layer(labels) is MolecularLayer.TRANSCRIPTOME

    def test_proteome(self):
        assert derive_molecular_layer(["proteomic profiling assay"]) is MolecularLayer.PROTEOME

    def test_epigenome(self):
        assert derive_molecular_layer(["ATAC-seq"]) is MolecularLayer.EPIGENOME

    def test_metabolome(self):
        assert derive_molecular_layer(["metabolite profiling assay"]) is MolecularLayer.METABOLOME

    def test_genome(self):
        assert derive_molecular_layer(["whole genome sequencing assay"]) is MolecularLayer.GENOME

    def test_case_insensitive(self):
        assert derive_molecular_layer(["RNA ASSAY"]) is MolecularLayer.TRANSCRIPTOME

    def test_no_anchor_defaults_to_unknown(self):
        assert derive_molecular_layer(["some bespoke assay", "thing"]) is MolecularLayer.UNKNOWN

    def test_empty_defaults_to_unknown(self):
        assert derive_molecular_layer([]) is MolecularLayer.UNKNOWN

    def test_blank_labels_ignored(self):
        assert derive_molecular_layer(["", "  "]) is MolecularLayer.UNKNOWN

    def test_specific_anchor_wins_over_broad(self):
        """When transcriptome and genome anchors co-occur, the earlier-listed
        (more specific) anchor wins deterministically."""
        labels = ["RNA assay", "whole genome sequencing assay"]
        assert derive_molecular_layer(labels) is MolecularLayer.TRANSCRIPTOME
