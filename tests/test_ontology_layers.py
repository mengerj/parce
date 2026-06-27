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
        (more specific) keyword wins deterministically."""
        labels = ["RNA assay", "whole genome sequencing assay"]
        assert derive_molecular_layer(labels) is MolecularLayer.TRANSCRIPTOME

    def test_10x_transcription_profiling_branch(self):
        """The 10x family never reaches 'RNA assay'; it is caught by the
        'transcription profiling' keyword on a parent-process label. This is the
        real live-EFO lineage exact-label matching used to miss (→ UNKNOWN)."""
        labels = [
            "10x 3' transcription profiling",
            "10x transcription profiling",
            "single cell library construction",
            "library preparation",
        ]
        assert derive_molecular_layer(labels) is MolecularLayer.TRANSCRIPTOME

    def test_substring_keyword_matches_within_label(self):
        """Matching is substring, not whole-label: ChIP's 'immunoprecipitation
        assay' / 'chromatin' ancestor labels classify it as epigenome."""
        assert (
            derive_molecular_layer(["immunoprecipitation assay", "DNA assay"])
            is MolecularLayer.EPIGENOME
        )

    def test_epigenome_dna_assay_beats_genome(self):
        """ATAC/ChIP/methylation carry a generic 'DNA assay' ancestor; the
        epigenome keyword must win over the broad GENOME 'dna' signals."""
        assert (
            derive_molecular_layer(["ATAC-seq", "DNA assay", "DNA-seq"]) is MolecularLayer.EPIGENOME
        )

    def test_bare_mass_spectrometry_is_unknown(self):
        """Mass spectrometry alone is ambiguous (proteome vs metabolome), so its
        lineage intentionally reaches no anchor."""
        labels = ["assay by mass spectrometry", "assay by instrument", "assay"]
        assert derive_molecular_layer(labels) is MolecularLayer.UNKNOWN
