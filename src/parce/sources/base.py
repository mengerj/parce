"""The :class:`SourceAdapter` contract.

An adapter is the only place network IO for a given repository lives. It does
two things and nothing more:

* ``discover(query)`` — resolve a query (a DOI, an accession, a search term) into
  a list of study references the adapter knows how to fetch.
* ``fetch(ref)`` — pull one reference into a source-shaped
  :class:`~parce.models.raw_record.RawRecord`.

Adapters never produce canonical KG nodes; mapping a ``RawRecord`` into the
canonical schema is the matching :class:`~parce.normalize.base.Normalizer`'s job.
Keeping the two split means a structured source (deterministic normalizer) and an
unstructured source (agent-backed normalizer) share the exact same adapter shape.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from parce.models.raw_record import RawRecord


@runtime_checkable
class SourceAdapter(Protocol):
    """Per-repository adapter: discover study references, fetch raw records."""

    #: Provenance label written onto every ``RawRecord`` this adapter emits.
    source_name: str

    def discover(self, query: str) -> list[str]:
        """Resolve a query into study references this adapter can ``fetch``."""
        ...

    def fetch(self, ref: str) -> RawRecord:
        """Fetch one study reference into a source-shaped ``RawRecord``."""
        ...
