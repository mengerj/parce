"""Graph assembly and cross-source merge.

The KG merger (:mod:`parce.graph.merge`) combines per-study
:class:`~parce.models.graph_schema.KnowledgeGraphOutput`s — one per normalized
source — into a single graph deduplicated by ontology ID, through which studies
from different sources link via shared entity nodes. Per-study assembly itself
lives in the source normalizers (``parce.normalize``); this package only joins
their outputs.
"""

from __future__ import annotations

from parce.graph.merge import (
    EntityProvenance,
    cross_source_entities,
    entity_provenance,
    merge_subgraphs,
)

__all__ = [
    "EntityProvenance",
    "cross_source_entities",
    "entity_provenance",
    "merge_subgraphs",
]
