"""Pydantic schemas for the canonical Knowledge Graph.

Source-agnostic node and edge types for an entity-centric graph that links
studies, datasets, and samples to biological entities (tissues, diseases,
species, perturbations, assays) via typed edges. Every source — structured or
agent-extracted — emits these same models; per-source variation lives entirely
in the adapters/normalizers, not here.

Two design rules are enforced by this schema:

- **Context is design, not data-inferred outcome.** ``CellType`` is intentionally
  absent from :class:`EntityType`: cell type is called from expression and would
  leak the signal the downstream model must learn.
- **Cross-source links are emergent.** Studies connect through shared
  ``ontology_id`` edge targets, never through any source-specific key.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EntityType(StrEnum):
    """Controlled vocabulary for biological entity categories.

    ``CellType`` is deliberately excluded — it is a data-inferred annotation
    (called from expression), not an experiment-design variable, and storing it
    would leak the downstream learning target.
    """

    DISEASE = "Disease"
    TISSUE = "Tissue"
    SPECIES = "Species"
    PERTURBATION = "Perturbation"
    ASSAY = "Assay"


class MolecularLayer(StrEnum):
    """Coarse molecular readout an assay measures — a controlled, cross-modality
    categorical the downstream model can condition on.

    Derived deterministically by walking an EFO ``assay`` term's ``is-a``
    ancestors to a pinned anchor class (see :mod:`parce.ontology.layers`); never
    re-strung from free text. ``UNKNOWN`` is the no-anchor default for assays
    whose lineage reaches none of the anchors.

    Defined here, the canonical-vocabulary home, so the ontology stage can target
    it now. It becomes a stored field on the study/dataset nodes in the
    schema-refinement PR (see docs/ROADMAP.md).
    """

    GENOME = "genome"
    EPIGENOME = "epigenome"
    TRANSCRIPTOME = "transcriptome"
    PROTEOME = "proteome"
    METABOLOME = "metabolome"
    UNKNOWN = "unknown"


class StudyNode(BaseModel):
    """A study (publication or repository accession), source-agnostic.

    Holds only normalized, design-describing fields. Raw free text (abstracts,
    full descriptions) lives in the per-source ``RawRecord``, not here.
    """

    model_config = ConfigDict(extra="forbid")

    study_id: str = Field(
        ...,
        description="Stable study identifier: a DOI or repository accession (e.g. GSE164378).",
    )
    title: str = Field(..., description="Study title.")
    source: str = Field(
        ...,
        description="Provenance of the study record (e.g. 'CELLxGENE', 'GEO', 'PRIDE').",
    )
    modality: str = Field(
        ...,
        description="High-level assay modality of the study (e.g. 'scRNA-seq', 'proteomics').",
    )


class DatasetNode(BaseModel):
    """A dataset belonging to a study; the link to its study is a typed edge."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., description="Source dataset identifier (e.g. CELLxGENE UUID).")
    data_uri: str = Field(
        ...,
        description="Remote URI for the dataset payload (e.g. s3://cellxgene-data-public/...).",
    )
    assay: str = Field(
        ...,
        description="Specific assay/technology (e.g. \"10x 3' v3\", 'Smart-seq2').",
    )
    cell_count: int = Field(..., description="Number of cells (or rows) in the dataset.")


class SampleNode(BaseModel):
    """A biological sample with experiment-*design* covariates only.

    Different sources populate different subsets of the covariates, so all of
    them are optional. Data-inferred annotations (cell type, cluster labels) are
    never recorded here. The link to a parent dataset/study is a typed edge.
    """

    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(..., description="Repository sample accession (e.g. GSM1234567).")
    data_uri: str | None = Field(
        default=None,
        description="URI to this sample's raw data, if the source exposes one.",
    )
    organism: str | None = Field(default=None, description="Species name (e.g. 'Mus musculus').")
    condition: str | None = Field(
        default=None,
        description="Experimental condition as designed (e.g. 'control', 'stimulated').",
    )
    perturbation: str | None = Field(
        default=None,
        description="Designed perturbation (e.g. a gene knockout, drug, dose).",
    )
    timepoint: str | None = Field(
        default=None,
        description="Designed sampling timepoint (e.g. '0h', 'day 7').",
    )
    subject: str | None = Field(
        default=None,
        description="Subject/donor/replicate identifier the sample belongs to.",
    )


class BiologicalEntityNode(BaseModel):
    """A biological concept grounded to an ontology term."""

    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType = Field(..., description="Category of biological entity.")
    ontology_id: str = Field(
        ...,
        description=(
            "Ontology identifier (e.g. 'UBERON:0000178' for blood, "
            "'MONDO:0005061' for lung disease, or 'unknown')."
        ),
    )
    name: str = Field(..., description="Human-readable name (e.g. 'blood').")


class GraphEdge(BaseModel):
    """A directed relationship between two nodes in the knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(
        ...,
        description="Source node id (study_id, dataset_id, sample_id, or ontology_id).",
    )
    target_id: str = Field(..., description="Identifier of the target node.")
    relation_type: str = Field(
        ...,
        description=(
            "Relationship label, e.g. 'EXTRACTED_FROM' (Dataset -> Study), "
            "'HAS_SAMPLE' (Dataset -> Sample), 'HAS_TISSUE' / 'HAS_CONDITION' "
            "(Dataset -> BiologicalEntity), 'MEASURED_WITH' (Dataset -> Assay), "
            "'STUDIES' (Study -> Species)."
        ),
    )


class KnowledgeGraphOutput(BaseModel):
    """Top-level wrapper: a complete knowledge graph for one or more studies."""

    model_config = ConfigDict(extra="forbid")

    studies: list[StudyNode] = Field(default_factory=list)
    datasets: list[DatasetNode] = Field(default_factory=list)
    samples: list[SampleNode] = Field(default_factory=list)
    biological_entities: list[BiologicalEntityNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
