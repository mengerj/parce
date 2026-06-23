"""Deterministic Knowledge Graph construction from tool outputs + LLM narrative.

The LLM only generates the ``experimental_narrative``.  All other nodes
and edges are assembled programmatically from the structured data returned
by the CELLxGENE and EuropePMC tools.
"""

from __future__ import annotations

import logging

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    PublicationNode,
)
from parce.tools.cellxgene_fetcher import _ORGANISM_ONTOLOGY

logger = logging.getLogger(__name__)

_CATEGORY_TO_ENTITY_TYPE: dict[str, EntityType] = {
    "cell_types": EntityType.CELL_TYPE,
    "tissues": EntityType.TISSUE,
    "diseases": EntityType.DISEASE,
    "assays": EntityType.ASSAY,
}

_CATEGORY_TO_RELATION: dict[str, str] = {
    "cell_types": "MEASURES",
    "tissues": "MEASURES",
    "diseases": "HAS_CONDITION",
    "assays": "MEASURED_WITH",
}


def build_knowledge_graph(
    paper_data: dict,
    cellxgene_data: dict,
    narrative: str,
) -> KnowledgeGraphOutput:
    """Assemble a complete ``KnowledgeGraphOutput`` from structured data.

    Parameters
    ----------
    paper_data:
        Dict with keys ``doi``, ``title``, ``abstract`` (from ``fetch_paper_metadata``).
    cellxgene_data:
        Dict with key ``datasets`` containing per-dataset metadata and
        ontology summaries (from ``fetch_cellxgene_datasets``).
    narrative:
        The LLM-generated experimental narrative string.
    """
    doi = paper_data["doi"]

    publication = PublicationNode(
        doi=doi,
        title=paper_data.get("title", ""),
        abstract=paper_data.get("abstract", ""),
        experimental_narrative=narrative,
    )

    datasets: list[DatasetNode] = []
    edges: list[GraphEdge] = []
    entity_registry: dict[str, BiologicalEntityNode] = {}
    species_seen: set[str] = set()

    for ds in cellxgene_data.get("datasets", []):
        dataset_id = ds["dataset_id"]

        datasets.append(DatasetNode(
            dataset_id=dataset_id,
            uri=ds["h5ad_uri"],
            modality=ds.get("modality", "unknown"),
            cell_count=ds["cell_count"],
        ))

        edges.append(GraphEdge(
            source_id=dataset_id,
            target_id=doi,
            relation_type="EXTRACTED_FROM",
        ))

        ontology = ds.get("ontology_summary", {})

        # Register species from the organism field
        organism_key = ontology.get("organism", "unknown")
        if organism_key in _ORGANISM_ONTOLOGY and organism_key not in species_seen:
            ont_id, name = _ORGANISM_ONTOLOGY[organism_key]
            species_seen.add(organism_key)
            entity_registry[ont_id] = BiologicalEntityNode(
                entity_type=EntityType.SPECIES,
                ontology_id=ont_id,
                name=name,
            )

        # Register entities and create edges per category
        for category, entity_type in _CATEGORY_TO_ENTITY_TYPE.items():
            relation = _CATEGORY_TO_RELATION[category]
            for term in ontology.get(category, []):
                ont_id = term.get("ontology_id", "unknown")
                name = term.get("name", "unknown")

                if ont_id not in entity_registry:
                    entity_registry[ont_id] = BiologicalEntityNode(
                        entity_type=entity_type,
                        ontology_id=ont_id,
                        name=name,
                    )

                edges.append(GraphEdge(
                    source_id=dataset_id,
                    target_id=ont_id,
                    relation_type=relation,
                ))

    # Publication -> Species edges
    for ont_id in species_seen:
        if ont_id in _ORGANISM_ONTOLOGY:
            resolved_id = _ORGANISM_ONTOLOGY[ont_id][0]
        else:
            resolved_id = ont_id
        edges.append(GraphEdge(
            source_id=doi,
            target_id=resolved_id,
            relation_type="STUDIES",
        ))

    kg = KnowledgeGraphOutput(
        publications=[publication],
        datasets=datasets,
        biological_entities=list(entity_registry.values()),
        edges=edges,
    )

    logger.info(
        "Built KG: publications=%d datasets=%d entities=%d edges=%d",
        len(kg.publications), len(kg.datasets),
        len(kg.biological_entities), len(kg.edges),
    )
    return kg
