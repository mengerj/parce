"""Derive a coarse :class:`~parce.models.graph_schema.MolecularLayer` from an
EFO assay term's ``is-a`` ancestry.

The classification is done by the *lineage*, not by re-parsing strings: we walk
the assay term's ancestors (via OLS) and match their labels against a small set
of pinned **anchor classes**. The anchors are keyed by their canonical EFO
**label**, not by term ID — the registry pins ontologies/anchors, not IDs
(docs/ARCHITECTURE.md §5), and OLS returns canonical labels for every ancestor.

PROVISIONAL anchor set: the exact EFO ancestor labels below are an informed
first cut. They are validated against the live EFO assay branch by the marked
integration test ``tests/test_ontology_integration.py``; correct/extend them
there as real lineages are observed. An assay whose ancestry reaches no anchor
falls back to :attr:`MolecularLayer.UNKNOWN` (the pinned no-anchor default).
"""

from __future__ import annotations

from collections.abc import Iterable

from parce.models.graph_schema import MolecularLayer

# Anchor EFO ancestor label (lower-cased) → molecular layer. Ordered
# most-specific first: when an assay's ancestry hits several anchors, the first
# match in this mapping wins, so narrower readouts beat broader ones.
_ANCHOR_LABELS: dict[str, MolecularLayer] = {
    # Transcriptome
    "rna assay": MolecularLayer.TRANSCRIPTOME,
    "transcription profiling assay": MolecularLayer.TRANSCRIPTOME,
    "transcription profiling by high throughput sequencing": MolecularLayer.TRANSCRIPTOME,
    # Epigenome (chromatin accessibility, methylation, histone marks)
    "atac-seq": MolecularLayer.EPIGENOME,
    "dna methylation profiling assay": MolecularLayer.EPIGENOME,
    "methylation profiling assay": MolecularLayer.EPIGENOME,
    "chromatin immunoprecipitation assay": MolecularLayer.EPIGENOME,
    # Proteome
    "proteomic profiling assay": MolecularLayer.PROTEOME,
    "protein assay": MolecularLayer.PROTEOME,
    "mass spectrometry assay": MolecularLayer.PROTEOME,
    # Metabolome
    "metabolite profiling assay": MolecularLayer.METABOLOME,
    "metabolomics assay": MolecularLayer.METABOLOME,
    # Genome (sequence/variation, kept last as the broadest DNA readout)
    "whole genome sequencing assay": MolecularLayer.GENOME,
    "genotyping assay": MolecularLayer.GENOME,
    "dna sequencing": MolecularLayer.GENOME,
}


def derive_molecular_layer(ancestor_labels: Iterable[str]) -> MolecularLayer:
    """Classify an assay from the labels of its ``is-a`` ancestors.

    ``ancestor_labels`` should include the assay term's own label plus its
    ancestors' labels. Matching is case-insensitive and exact against the pinned
    anchor labels; the first anchor (in :data:`_ANCHOR_LABELS` order) present in
    the lineage wins. Returns :attr:`MolecularLayer.UNKNOWN` when none match.
    """
    present = {label.strip().lower() for label in ancestor_labels if label}
    for anchor, layer in _ANCHOR_LABELS.items():
        if anchor in present:
            return layer
    return MolecularLayer.UNKNOWN
