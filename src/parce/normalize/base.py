"""The :class:`Normalizer` contract.

A normalizer maps one source's :class:`~parce.models.raw_record.RawRecord` into
canonical KG nodes and edges. The implementation may be:

* **deterministic** — a pure structural mapping, used when the source already
  ships structured, ontology-grounded metadata (e.g. CELLxGENE); or
* **agent-backed** — an LLM constrained to emit the canonical schema via
  ``response_format``, used for free-text sources (e.g. GEO, PRIDE).

Both kinds return the same :class:`~parce.models.graph_schema.KnowledgeGraphOutput`,
so everything downstream (merge, export) is source-agnostic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from parce.models.graph_schema import KnowledgeGraphOutput
from parce.models.raw_record import RawRecord


@runtime_checkable
class Normalizer(Protocol):
    """Maps a source-shaped ``RawRecord`` into canonical nodes and edges."""

    def normalize(self, record: RawRecord) -> KnowledgeGraphOutput:
        """Return the canonical single-study subgraph for ``record``."""
        ...
