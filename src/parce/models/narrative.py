"""Pydantic schemas for the structured experiment narrative output.

These models define the JSON structure the agent produces via structured output
(``response_format``).  They also serve as validation schemas for any downstream
consumer of the narrative data.

All models set ``extra="forbid"`` which is required by the Azure OpenAI
structured-output API for nested Pydantic models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DataURI(BaseModel):
    """A URI reference to a raw data file (e.g. FASTQ, BAM) in a public repository."""

    model_config = ConfigDict(extra="forbid")

    uri: str = Field(
        ...,
        description="Full URI to the data file (e.g. https://sra-pub-run-odp.s3.amazonaws.com/...).",
    )
    file_type: str = Field(
        ...,
        description="File format such as FASTQ, BAM, or H5AD.",
    )
    description: str | None = Field(
        default=None,
        description="Optional human-readable note about this data file.",
    )


class SampleRecord(BaseModel):
    """Metadata for a single biological sample within an experiment."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(..., description="Repository sample accession (e.g. GSM1234567).")
    organism: str = Field(..., description="Species name (e.g. Mus musculus).")
    strain: str | None = Field(default=None, description="Strain or genetic background.")
    cell_type: str | None = Field(
        default=None, description="Cell type profiled (e.g. CD8+ T cell)."
    )
    tissue: str | None = Field(default=None, description="Tissue of origin (e.g. spleen).")
    condition: str | None = Field(
        default=None,
        description="Experimental condition (e.g. knockout, stimulated, control).",
    )
    knockout_gene: str | None = Field(
        default=None,
        description="Gene knocked out, if applicable.",
    )
    data_uris: list[DataURI] = Field(
        default_factory=list,
        description="Raw data files associated with this sample.",
    )


class ExperimentNarrative(BaseModel):
    """Top-level structured output: a narrative description of a public experiment
    interleaved with sample records and data URIs.

    This is the schema passed as ``response_format`` to the agent so the LLM
    returns strictly typed JSON.
    """

    model_config = ConfigDict(extra="forbid")

    accession: str = Field(..., description="Primary accession (e.g. GSE164378).")
    title: str = Field(..., description="Experiment title as listed in the repository.")
    summary: str = Field(
        ...,
        description=(
            "A narrative paragraph describing how the data was obtained, "
            "including organism, experimental design, and sequencing approach."
        ),
    )
    platform: str | None = Field(
        default=None,
        description="Sequencing platform (e.g. Illumina NovaSeq 6000).",
    )
    samples: list[SampleRecord] = Field(
        default_factory=list,
        description="Individual sample records with metadata and data URIs.",
    )
