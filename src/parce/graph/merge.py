"""Cross-source KG merge: many per-study subgraphs → one knowledge graph.

Each source normalizer emits a per-study
:class:`~parce.models.graph_schema.KnowledgeGraphOutput` (a *subgraph*). This stage
combines subgraphs from *different* sources into a single graph in which a
biological entity that several studies share — a tissue, disease, species, or
assay — is **one** node. That single shared node is what links a CELLxGENE study
and a GEO study that both touch e.g. ``UBERON:0002048`` (lung): the cross-source
connection is *emergent* from the shared ``ontology_id`` (docs/ARCHITECTURE.md §1,
§4), not from any source-specific key.

What merges and what does not:

* **Biological entities dedup by ``ontology_id``** — the same term from two sources
  collapses to one node (its name back-filled if one source left it ``unknown``).
* **Studies / datasets / samples are kept**, deduped only by their own identifier
  (``study_id`` / ``dataset_id`` / ``sample_id``). Cross-source IDs never collide
  (a DOI vs. a ``GSEnnnnn``), so this only guards against the same subgraph being
  merged twice — keeping the merge idempotent.
* **Edges are preserved intact** — only exact duplicates
  ``(source_id, target_id, relation_type)`` collapse. This is what "provenance on
  edges" means: an entity is *not* merged away, so every edge that pointed at it
  still records which study/dataset touched it. Provenance is therefore never
  stored redundantly on a node (which could drift — see the PR 2 "containment is
  edge-only" decision); it is *derived* from the retained edges by
  :func:`entity_provenance`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    GraphEdge,
    KnowledgeGraphOutput,
    SampleNode,
    StudyNode,
)

logger = logging.getLogger(__name__)

_UNKNOWN = "unknown"
_EXTRACTED_FROM = "EXTRACTED_FROM"
_HAS_SAMPLE = "HAS_SAMPLE"


def merge_subgraphs(subgraphs: Iterable[KnowledgeGraphOutput]) -> KnowledgeGraphOutput:
    """Merge per-study subgraphs into one KG, deduped by ontology entity ID.

    Studies, datasets, and samples from every subgraph are kept (deduped by their
    own identifier); biological entities are deduped by ``ontology_id`` so a term
    several studies share becomes a single node through which those studies link.
    Edges are preserved (only exact duplicates collapse), so each retained edge
    still records which study/dataset touches a shared entity. The merge is
    order-preserving (first-seen wins) and idempotent.
    """
    studies: dict[str, StudyNode] = {}
    datasets: dict[str, DatasetNode] = {}
    samples: dict[str, SampleNode] = {}
    entities: dict[str, BiologicalEntityNode] = {}
    edges: dict[tuple[str, str, str], GraphEdge] = {}

    n_subgraphs = 0
    for sg in subgraphs:
        n_subgraphs += 1
        for study in sg.studies:
            studies.setdefault(study.study_id, study)
        for dataset in sg.datasets:
            datasets.setdefault(dataset.dataset_id, dataset)
        for sample in sg.samples:
            samples.setdefault(sample.sample_id, sample)
        for entity in sg.biological_entities:
            existing = entities.get(entity.ontology_id)
            entities[entity.ontology_id] = (
                entity if existing is None else _merge_entity(existing, entity)
            )
        for edge in sg.edges:
            edges.setdefault((edge.source_id, edge.target_id, edge.relation_type), edge)

    merged = KnowledgeGraphOutput(
        studies=list(studies.values()),
        datasets=list(datasets.values()),
        samples=list(samples.values()),
        biological_entities=list(entities.values()),
        edges=list(edges.values()),
    )
    logger.info(
        "Merged %d subgraph(s): studies=%d datasets=%d samples=%d entities=%d edges=%d",
        n_subgraphs,
        len(merged.studies),
        len(merged.datasets),
        len(merged.samples),
        len(merged.biological_entities),
        len(merged.edges),
    )
    return merged


def _merge_entity(
    existing: BiologicalEntityNode, incoming: BiologicalEntityNode
) -> BiologicalEntityNode:
    """Reconcile two nodes for the same ``ontology_id`` (first-seen wins).

    Keeps ``existing`` but back-fills its name from ``incoming`` when one source
    left the term ungrounded (``""``/``"unknown"``). A type disagreement keeps the
    first type and is logged — it signals a genuine cross-source modelling clash.
    """
    if existing.entity_type != incoming.entity_type:
        logger.warning(
            "Entity %s typed as both %s and %s; keeping %s",
            existing.ontology_id,
            existing.entity_type,
            incoming.entity_type,
            existing.entity_type,
        )
    if existing.name in ("", _UNKNOWN) and incoming.name not in ("", _UNKNOWN):
        return existing.model_copy(update={"name": incoming.name})
    return existing


@dataclass(frozen=True)
class EntityProvenance:
    """Which studies (and their source repositories) touch one shared entity."""

    ontology_id: str
    studies: frozenset[str]
    sources: frozenset[str]


def entity_provenance(graph: KnowledgeGraphOutput) -> dict[str, EntityProvenance]:
    """Map each biological entity to the studies/sources that touch it.

    Derived from the graph's edges (never stored on a node): an edge into an
    entity is attributed to the study that owns its origin node — the study itself
    (GEO study-level edges, ``STUDIES``), the study reached via ``EXTRACTED_FROM``
    (CELLxGENE dataset-level edges), or via ``HAS_SAMPLE`` (sample-level edges).
    The owning study's :attr:`StudyNode.source` gives the repository, so an entity
    whose ``sources`` has more than one member is a cross-source link.
    """
    study_source = {s.study_id: s.source for s in graph.studies}
    study_ids = set(study_source)
    entity_ids = {e.ontology_id for e in graph.biological_entities}

    # node id -> owning study id (study owns itself; dataset/sample owned via edge).
    owner: dict[str, str] = {sid: sid for sid in study_ids}
    for edge in graph.edges:
        if edge.relation_type == _EXTRACTED_FROM and edge.target_id in study_ids:
            owner[edge.source_id] = edge.target_id  # dataset -> study
        elif edge.relation_type == _HAS_SAMPLE and edge.source_id in study_ids:
            owner[edge.target_id] = edge.source_id  # sample -> study

    studies_by_entity: dict[str, set[str]] = {eid: set() for eid in entity_ids}
    for edge in graph.edges:
        if edge.target_id not in entity_ids:
            continue
        owning_study = owner.get(edge.source_id)
        if owning_study is not None:
            studies_by_entity[edge.target_id].add(owning_study)

    return {
        eid: EntityProvenance(
            ontology_id=eid,
            studies=frozenset(touching),
            sources=frozenset(study_source[s] for s in touching if s in study_source),
        )
        for eid, touching in studies_by_entity.items()
    }


def cross_source_entities(graph: KnowledgeGraphOutput) -> dict[str, EntityProvenance]:
    """Entities touched by studies from two or more distinct source repositories.

    These are the graph's cross-source links — the shared-context nodes that join
    studies from different repositories (and, later, different modalities).
    """
    return {eid: prov for eid, prov in entity_provenance(graph).items() if len(prov.sources) >= 2}
