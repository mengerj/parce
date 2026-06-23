"""Pydantic schemas for the Knowledge Graph output.

Defines node and edge types for an entity-centric graph that links
publications, datasets, and biological entities (cell types, tissues,
diseases, species, perturbations) via typed edges.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EntityType(StrEnum):
    """Controlled vocabulary for biological entity categories."""

    DISEASE = "Disease"
    CELL_TYPE = "CellType"
    TISSUE = "Tissue"
    SPECIES = "Species"
    PERTURBATION = "Perturbation"
    ASSAY = "Assay"


class PublicationNode(BaseModel):
    """A published study identified by DOI."""

    model_config = ConfigDict(extra="forbid")

    doi: str = Field(
        ..., description="Digital Object Identifier (e.g. 10.1038/s41586-023-05869-0)."
    )
    title: str = Field(..., description="Publication title.")
    abstract: str = Field(..., description="Full abstract text.")
    experimental_narrative: str = Field(
        ...,
        description=(
            "LLM-generated concise narrative synthesising the abstract and "
            "the structured CELLxGENE ontology data into a description of "
            "how the data was obtained."
        ),
    )


class DatasetNode(BaseModel):
    """A single-cell dataset hosted on CELLxGENE."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., description="CELLxGENE dataset UUID.")
    uri: str = Field(
        ...,
        description="Remote URI for the H5AD file (e.g. s3://cellxgene-data-public/...).",
    )
    modality: str = Field(
        ...,
        description="Assay modality (e.g. 'scRNA-seq', '10x 3' v3', 'Smart-seq2').",
    )
    cell_count: int = Field(..., description="Total number of cells in the dataset.")


class BiologicalEntityNode(BaseModel):
    """A biological concept grounded to an ontology term."""

    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType = Field(..., description="Category of biological entity.")
    ontology_id: str = Field(
        ...,
        description=(
            "Ontology identifier (e.g. 'CL:0000084' for T cell, "
            "'MONDO:0005061' for lung disease, or 'unknown')."
        ),
    )
    name: str = Field(..., description="Human-readable name (e.g. 'T cell').")


class GraphEdge(BaseModel):
    """A directed relationship between two nodes in the knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(
        ..., description="Identifier of the source node (DOI or dataset_id or ontology_id)."
    )
    target_id: str = Field(..., description="Identifier of the target node.")
    relation_type: str = Field(
        ...,
        description=(
            "Relationship label, e.g. 'EXTRACTED_FROM' (Dataset -> Publication), "
            "'MEASURES' (Dataset -> BiologicalEntity), "
            "'HAS_CONDITION' (Dataset -> BiologicalEntity)."
        ),
    )


class KnowledgeGraphOutput(BaseModel):
    """Top-level wrapper returned by the agent: a complete knowledge graph
    for one or more publications and their associated datasets."""

    model_config = ConfigDict(extra="forbid")

    publications: list[PublicationNode] = Field(default_factory=list)
    datasets: list[DatasetNode] = Field(default_factory=list)
    biological_entities: list[BiologicalEntityNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class NarrativeOutput(BaseModel):
    """Minimal schema for the LLM narrative generation step.

    Only the experimental_narrative requires LLM intelligence;
    all other KG fields are assembled programmatically.
    """

    experimental_narrative: str = Field(
        ...,
        description=(
            "A concise paragraph synthesising the publication abstract "
            "with the structured CELLxGENE ontology data to explain "
            "how the data was obtained."
        ),
    )
