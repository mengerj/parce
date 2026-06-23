"""Deterministic Knowledge Graph construction from CELLxGENE + paper metadata.

This is the CELLxGENE ingestion path: it assembles canonical nodes and edges
programmatically from the structured data returned by the CELLxGENE and
EuropePMC tools. No LLM is involved. (It is slated to become a proper
``SourceAdapter``/``Normalizer`` in PR 3 — see docs/ROADMAP.md.)

``CellType`` is intentionally not extracted: it is a data-inferred annotation,
not an experiment-design variable. CELLxGENE Census is dataset-level, so no
``SampleNode`` records are emitted here yet (see ARCHITECTURE.md, open question
on sample granularity).
"""

from __future__ import annotations

import logging

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    StudyNode,
)
from parce.tools.cellxgene_fetcher import _ORGANISM_ONTOLOGY

logger = logging.getLogger(__name__)

# Provenance + high-level modality for everything built by this path.
_SOURCE = "CELLxGENE"
_STUDY_MODALITY = "scRNA-seq"

# Ontology categories from CELLxGENE that become design-context entities. Cell
# types are deliberately omitted (data-inferred → leakage).
_CATEGORY_TO_ENTITY_TYPE: dict[str, EntityType] = {
    "tissues": EntityType.TISSUE,
    "diseases": EntityType.DISEASE,
    "assays": EntityType.ASSAY,
}

_CATEGORY_TO_RELATION: dict[str, str] = {
    "tissues": "HAS_TISSUE",
    "diseases": "HAS_CONDITION",
    "assays": "MEASURED_WITH",
}


def build_knowledge_graph(
    paper_data: dict,
    cellxgene_data: dict,
) -> KnowledgeGraphOutput:
    """Assemble a canonical ``KnowledgeGraphOutput`` from structured data.

    Parameters
    ----------
    paper_data:
        Dict with keys ``doi``, ``title`` (from ``fetch_paper_metadata``).
    cellxgene_data:
        Dict with key ``datasets`` containing per-dataset metadata and
        ontology summaries (from ``fetch_cellxgene_datasets``).
    """
    study_id = paper_data["doi"]

    study = StudyNode(
        study_id=study_id,
        title=paper_data.get("title", ""),
        source=_SOURCE,
        modality=_STUDY_MODALITY,
    )

    datasets: list[DatasetNode] = []
    edges: list[GraphEdge] = []
    entity_registry: dict[str, BiologicalEntityNode] = {}
    species_seen: set[str] = set()

    for ds in cellxgene_data.get("datasets", []):
        dataset_id = ds["dataset_id"]

        datasets.append(
            DatasetNode(
                dataset_id=dataset_id,
                data_uri=ds["h5ad_uri"],
                assay=ds.get("modality", "unknown"),
                cell_count=ds["cell_count"],
            )
        )

        edges.append(
            GraphEdge(
                source_id=dataset_id,
                target_id=study_id,
                relation_type="EXTRACTED_FROM",
            )
        )

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

        # Register entities and create edges per design-context category
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

                edges.append(
                    GraphEdge(
                        source_id=dataset_id,
                        target_id=ont_id,
                        relation_type=relation,
                    )
                )

    # Study -> Species edges
    for organism_key in species_seen:
        species_id = _ORGANISM_ONTOLOGY[organism_key][0]
        edges.append(
            GraphEdge(
                source_id=study_id,
                target_id=species_id,
                relation_type="STUDIES",
            )
        )

    kg = KnowledgeGraphOutput(
        studies=[study],
        datasets=datasets,
        samples=[],
        biological_entities=list(entity_registry.values()),
        edges=edges,
    )

    logger.info(
        "Built KG: studies=%d datasets=%d samples=%d entities=%d edges=%d",
        len(kg.studies),
        len(kg.datasets),
        len(kg.samples),
        len(kg.biological_entities),
        len(kg.edges),
    )
    return kg
