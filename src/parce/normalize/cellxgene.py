"""Deterministic normalizer: a CELLxGENE ``RawRecord`` → canonical KG nodes.

No LLM is involved: CELLxGENE Census already ships ontology-grounded terms, so
this is a pure structural mapping. Two design rules show up directly here:

* **Cell type is never consumed** — the adapter does not even read it
  (data-inferred → leakage; see docs/ARCHITECTURE.md §1).
* **Census is dataset-level**, not per-sample in the GEO sense, so no
  ``SampleNode`` records are emitted yet (open question in ARCHITECTURE §7).

The free-text → ontology-ID step (here, organism string → NCBITaxon) is a
hardcoded map for now; it becomes the shared OntologyResolver stage in PR 4.
"""

from __future__ import annotations

import logging
from typing import Any

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    StudyNode,
)
from parce.models.raw_record import RawRecord

logger = logging.getLogger(__name__)

# High-level study modality for everything CELLxGENE ingests. (Refined into an
# EFO ``assay`` term + derived ``molecular_layer`` in PR 4.)
_STUDY_MODALITY = "scRNA-seq"

# Organism free-text (as Census returns it) → (NCBITaxon ID, canonical name).
# Stand-in for the PR 4 OntologyResolver.
_ORGANISM_ONTOLOGY: dict[str, tuple[str, str]] = {
    "Homo sapiens": ("NCBITaxon:9606", "Homo sapiens"),
    "Mus musculus": ("NCBITaxon:10090", "Mus musculus"),
    "homo_sapiens": ("NCBITaxon:9606", "Homo sapiens"),
    "mus_musculus": ("NCBITaxon:10090", "Mus musculus"),
}

# Ontology categories that become design-context entities. Cell types are
# deliberately absent (data-inferred → leakage).
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


class CellxgeneNormalizer:
    """:class:`~parce.normalize.base.Normalizer` for CELLxGENE ``RawRecord``s."""

    def normalize(self, record: RawRecord) -> KnowledgeGraphOutput:
        """Assemble the canonical single-study subgraph for one CELLxGENE study."""
        study_id = record.study_id

        study = StudyNode(
            study_id=study_id,
            title=record.title,
            source=record.source,
            modality=_STUDY_MODALITY,
        )

        datasets: list[DatasetNode] = []
        edges: list[GraphEdge] = []
        entity_registry: dict[str, BiologicalEntityNode] = {}
        species_seen: set[str] = set()

        for ds in record.payload.get("datasets", []):
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

            ontology: dict[str, Any] = ds.get("ontology_summary", {})

            # Register species from the organism field.
            organism_key = ontology.get("organism", "unknown")
            if organism_key in _ORGANISM_ONTOLOGY and organism_key not in species_seen:
                ont_id, name = _ORGANISM_ONTOLOGY[organism_key]
                species_seen.add(organism_key)
                entity_registry[ont_id] = BiologicalEntityNode(
                    entity_type=EntityType.SPECIES,
                    ontology_id=ont_id,
                    name=name,
                )

            # Register entities and create edges per design-context category.
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

        # Study → Species edges.
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
            "Normalized CELLxGENE study=%s: datasets=%d entities=%d edges=%d",
            study_id,
            len(kg.datasets),
            len(kg.biological_entities),
            len(kg.edges),
        )
        return kg
