"""Derive a coarse :class:`~parce.models.graph_schema.MolecularLayer` from an
EFO assay term's ``is-a`` ancestry.

The classification is done by the *lineage*, not by re-parsing the assay's free
text: we walk the assay term's ancestors (via OLS) and match their labels — plus
the assay's own label — against a small set of pinned **anchor keywords**.

Why keywords (substring), not exact full labels: the live EFO assay branch is
inconsistent. Some readouts announce themselves in an ancestor's label
("RNA assay"), others only in a *parent process* label ("10x 3' transcription
profiling" — the 10x family never reaches "RNA assay"), and several (ATAC-seq,
ChIP-seq, methylation, WGS) collapse to a generic "DNA assay" ancestor whose
distinguishing signal survives only in the term's own label. Ordered
case-insensitive substring matching against distinctive phrases handles all of
these; exact full-label matching cannot.

The keyword set is validated against the live EFO branch by the marked
integration test ``tests/test_ontology_integration.py``; extend it there as new
modalities (GEO bulk assays, PRIDE proteomics) bring real lineages. Order
matters: the first keyword (top-to-bottom) present in the lineage wins, so the
more specific epigenome DNA assays beat the broad GENOME ``DNA``/``whole genome``
signals. An assay whose lineage matches no keyword falls back to
:attr:`MolecularLayer.UNKNOWN` (the pinned no-anchor default) — e.g. bare
"mass spectrometry", which is genuinely ambiguous between proteome and
metabolome until a more specific term is known.
"""

from __future__ import annotations

from collections.abc import Iterable

from parce.models.graph_schema import MolecularLayer

# Ordered (substring keyword, molecular layer). The first keyword present in the
# lineage (case-insensitive) wins, so this list runs most-specific → broadest:
# the transcriptome/epigenome/proteome/metabolome readouts are matched before the
# broad GENOME DNA signals, which would otherwise swallow ATAC/ChIP/methylation
# (all of which carry a generic "DNA assay" ancestor).
_ANCHOR_KEYWORDS: tuple[tuple[str, MolecularLayer], ...] = (
    # Transcriptome — covers every CELLxGENE assay: the 10x family via
    # "transcription profiling", scRNA/Smart-seq/spatial via "RNA assay"/"RNA
    # sequencing"/"transcriptom".
    ("transcription profiling", MolecularLayer.TRANSCRIPTOME),
    ("rna sequencing", MolecularLayer.TRANSCRIPTOME),
    ("rna-seq", MolecularLayer.TRANSCRIPTOME),
    ("rna assay", MolecularLayer.TRANSCRIPTOME),
    ("transcriptom", MolecularLayer.TRANSCRIPTOME),
    # Epigenome — chromatin accessibility, methylation, histone marks. Listed
    # before GENOME so these DNA-branch assays don't fall through to "DNA assay".
    ("atac", MolecularLayer.EPIGENOME),
    ("methylation", MolecularLayer.EPIGENOME),
    ("bisulfite", MolecularLayer.EPIGENOME),
    ("chip-seq", MolecularLayer.EPIGENOME),
    ("immunoprecipitation", MolecularLayer.EPIGENOME),
    ("chromatin", MolecularLayer.EPIGENOME),
    ("histone", MolecularLayer.EPIGENOME),
    # Proteome.
    ("proteom", MolecularLayer.PROTEOME),
    ("protein assay", MolecularLayer.PROTEOME),
    # Metabolome.
    ("metabolom", MolecularLayer.METABOLOME),
    ("metabolite", MolecularLayer.METABOLOME),
    # Genome — DNA sequence/variation, the broadest DNA readout (kept last).
    ("whole genome", MolecularLayer.GENOME),
    ("genome sequencing", MolecularLayer.GENOME),
    ("genome shotgun", MolecularLayer.GENOME),
    ("genotyping", MolecularLayer.GENOME),
    ("dna sequencing", MolecularLayer.GENOME),
    ("exome", MolecularLayer.GENOME),
    ("dna-seq", MolecularLayer.GENOME),
)


def derive_molecular_layer(ancestor_labels: Iterable[str]) -> MolecularLayer:
    """Classify an assay from the labels of its ``is-a`` ancestors.

    ``ancestor_labels`` should include the assay term's own label plus its
    ancestors' labels (the resolver appends the former). Matching is
    case-insensitive substring against the pinned anchor keywords; the first
    keyword (in :data:`_ANCHOR_KEYWORDS` order) found anywhere in the lineage
    wins. Returns :attr:`MolecularLayer.UNKNOWN` when none match.
    """
    present = [label.strip().lower() for label in ancestor_labels if label and label.strip()]
    for keyword, layer in _ANCHOR_KEYWORDS:
        if any(keyword in label for label in present):
            return layer
    return MolecularLayer.UNKNOWN
