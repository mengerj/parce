"""Deterministic normalizer: a CELLxGENE ``RawRecord`` → canonical KG nodes.

No LLM is involved: CELLxGENE Census already ships ontology-grounded terms, so
this is a pure structural mapping. Three design rules show up directly here:

* **Cell type is never consumed** — the adapter does not even read it
  (data-inferred → leakage; see docs/ARCHITECTURE.md §1).
* **Census is dataset-level**, not per-sample in the GEO sense, so no
  ``SampleNode`` records are emitted yet (open question in ARCHITECTURE §7).
* **Organism strings are grounded via the shared OntologyResolver**, not a
  hardcoded map. Tissue/disease/assay already arrive as ontology IDs from
  Census, so only the bare organism string needs runtime resolution (to
  NCBITaxon, via OLS). An organism that fails to resolve is skipped rather than
  emitted ungrounded.
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
from parce.ontology import Facet, OntologyResolver, ResolvedTerm, TermResolver

logger = logging.getLogger(__name__)

# High-level study modality for everything CELLxGENE ingests. (Refined into an
# EFO ``assay`` term + derived ``molecular_layer`` in the schema-refinement PR.)
_STUDY_MODALITY = "scRNA-seq"

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
    """:class:`~parce.normalize.base.Normalizer` for CELLxGENE ``RawRecord``s.

    Takes a :class:`~parce.ontology.base.TermResolver` (default: a real
    :class:`~parce.ontology.resolver.OntologyResolver`) used to ground organism
    strings. Inject a deterministic fake to keep unit tests offline.
    """

    def __init__(self, resolver: TermResolver | None = None) -> None:
        self._resolver: TermResolver = resolver if resolver is not None else OntologyResolver()

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
        # Resolved species (by NCBITaxon ID), and a per-record memo of organism
        # string → resolution so the same string is grounded at most once.
        species_ids: set[str] = set()
        organism_cache: dict[str, ResolvedTerm | None] = {}

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

            # Ground the organism string to a NCBITaxon term via the resolver.
            organism_text = ontology.get("organism", "unknown")
            species = self._resolve_organism(organism_text, organism_cache)
            if species is not None and species.ontology_id not in species_ids:
                species_ids.add(species.ontology_id)
                entity_registry[species.ontology_id] = BiologicalEntityNode(
                    entity_type=EntityType.SPECIES,
                    ontology_id=species.ontology_id,
                    name=species.name,
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
        for species_id in species_ids:
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

    def _resolve_organism(
        self, organism_text: str, memo: dict[str, ResolvedTerm | None]
    ) -> ResolvedTerm | None:
        """Resolve an organism string to a NCBITaxon term, memoised per record."""
        if organism_text not in memo:
            memo[organism_text] = self._resolver.resolve_term(organism_text, Facet.ORGANISM)
        return memo[organism_text]
