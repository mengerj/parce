"""Source-shaped intermediate record that bridges adapters and normalizers.

A :class:`SourceAdapter` produces ``RawRecord`` objects; the matching
:class:`~parce.normalize.base.Normalizer` consumes them and emits canonical KG
nodes. The record is *source-shaped*, not canonical: its ``payload`` holds
whatever structure the repository exposes (free text, nested dicts, ontology
summaries). The canonical schema is imposed downstream, in the normalizer.

The identifying fields ``source``, ``study_id`` and ``title`` are lifted out of
the payload because every source has them and every normalizer needs them;
everything else stays inside ``payload``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawRecord(BaseModel):
    """One study's data as returned by a source adapter, before normalization."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        ...,
        description="Provenance label written by the adapter (e.g. 'CELLxGENE', 'GEO').",
    )
    study_id: str = Field(
        ...,
        description="Stable study identifier: a DOI or repository accession.",
    )
    title: str = Field(
        default="",
        description="Study title, if the source exposes one (empty otherwise).",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-shaped raw data consumed by the matching Normalizer.",
    )
