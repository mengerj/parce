"""Deterministic normalizer: a CELLxGENE ``RawRecord`` → canonical KG nodes.

No LLM is involved: CELLxGENE Census already ships ontology-grounded terms, so
this is a pure structural mapping. The design rules show up directly here:

* **Cell type is never consumed** — the adapter does not even read it
  (data-inferred → leakage; see docs/ARCHITECTURE.md §1).
* **Census is dataset-level**, not per-sample in the GEO sense, so no
  ``SampleNode`` records are emitted yet (open question in ARCHITECTURE §7).
* **Organism strings are grounded via the shared OntologyResolver**, not a
  hardcoded map. Tissue/disease/assay already arrive as ontology IDs from
  Census, so only the bare organism string needs runtime resolution (to
  NCBITaxon, via OLS). An organism that fails to resolve is skipped rather than
  emitted ungrounded.
* **Assay is stored as its EFO term ID plus a derived ``molecular_layer``**, not
  a free-text modality string (ARCHITECTURE §5). Census already grounds the
  assay (it ships the EFO ID alongside the name), so the normalizer *picks* that
  ID rather than re-resolving it; the resolver is used only to walk the EFO
  lineage for the coarse ``molecular_layer``.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from parce.models.graph_schema import (
    BiologicalEntityNode,
    DatasetNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    MolecularLayer,
    StudyNode,
)
from parce.models.raw_record import RawRecord
from parce.ontology import Facet, OntologyResolver, OntologyService, ResolvedTerm

logger = logging.getLogger(__name__)

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

_UNKNOWN_ASSAY = "unknown"


class CellxgeneNormalizer:
    """:class:`~parce.normalize.base.Normalizer` for CELLxGENE ``RawRecord``s.

    Takes an :class:`~parce.ontology.base.OntologyService` (default: a real
    :class:`~parce.ontology.resolver.OntologyResolver`) used to ground organism
    strings and to derive each assay's ``molecular_layer``. Inject a
    deterministic fake to keep unit tests offline.
    """

    def __init__(self, resolver: OntologyService | None = None) -> None:
        self._resolver: OntologyService = resolver if resolver is not None else OntologyResolver()

    def normalize(self, record: RawRecord) -> KnowledgeGraphOutput:
        """Assemble the canonical single-study subgraph for one CELLxGENE study."""
        study_id = record.study_id

        datasets: list[DatasetNode] = []
        edges: list[GraphEdge] = []
        entity_registry: dict[str, BiologicalEntityNode] = {}
        # Resolved species (by NCBITaxon ID), and a per-record memo of organism
        # string → resolution so the same string is grounded at most once.
        species_ids: set[str] = set()
        organism_cache: dict[str, ResolvedTerm | None] = {}
        # Per-record memos so each distinct assay term is layer-derived once, and
        # the study's representative assay can be chosen by frequency.
        layer_cache: dict[str, MolecularLayer] = {}
        assay_labels: dict[str, str] = {}
        assay_counts: Counter[str] = Counter()

        for ds in record.payload.get("datasets", []):
            dataset_id = ds["dataset_id"]
            ontology: dict[str, Any] = ds.get("ontology_summary", {})

            assay_id, assay_label = _select_assay(ontology)
            assay_counts[assay_id] += 1
            assay_labels.setdefault(assay_id, assay_label)

            datasets.append(
                DatasetNode(
                    dataset_id=dataset_id,
                    data_uri=ds["h5ad_uri"],
                    assay=assay_id,
                    molecular_layer=self._layer_for(assay_id, assay_label, layer_cache),
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

        # The study's representative assay is the most frequent across its
        # datasets (CELLxGENE collections are single-modality in practice); its
        # layer is reused from the per-dataset memo.
        study_assay = assay_counts.most_common(1)[0][0] if assay_counts else _UNKNOWN_ASSAY
        study = StudyNode(
            study_id=study_id,
            title=record.title,
            source=record.source,
            assay=study_assay,
            molecular_layer=self._layer_for(
                study_assay, assay_labels.get(study_assay, study_assay), layer_cache
            ),
        )

        kg = KnowledgeGraphOutput(
            studies=[study],
            datasets=datasets,
            samples=[],
            biological_entities=list(entity_registry.values()),
            edges=edges,
        )

        logger.info(
            "Normalized CELLxGENE study=%s: datasets=%d entities=%d edges=%d layer=%s",
            study_id,
            len(kg.datasets),
            len(kg.biological_entities),
            len(kg.edges),
            study.molecular_layer,
        )
        return kg

    def _layer_for(
        self, assay_id: str, assay_label: str, memo: dict[str, MolecularLayer]
    ) -> MolecularLayer:
        """Derive (and memoise) the molecular layer for one assay term.

        Only EFO assay IDs are walked — the lineage walk is EFO-specific and an
        ungrounded ``'unknown'`` assay has no lineage — so anything else maps to
        :attr:`MolecularLayer.UNKNOWN` without a network call.
        """
        if assay_id not in memo:
            if assay_id.startswith("EFO:"):
                memo[assay_id] = self._resolver.molecular_layer(assay_id, assay_label=assay_label)
            else:
                memo[assay_id] = MolecularLayer.UNKNOWN
        return memo[assay_id]

    def _resolve_organism(
        self, organism_text: str, memo: dict[str, ResolvedTerm | None]
    ) -> ResolvedTerm | None:
        """Resolve an organism string to a NCBITaxon term, memoised per record."""
        if organism_text not in memo:
            memo[organism_text] = self._resolver.resolve_term(organism_text, Facet.ORGANISM)
        return memo[organism_text]


def _select_assay(ontology: dict[str, Any]) -> tuple[str, str]:
    """Pick the dataset's grounded (EFO) assay ID and label from the payload.

    Census ships the assay already grounded: ``ontology['assays']`` is a list of
    ``{name, ontology_id}`` and ``ontology['modality']`` is the dominant assay's
    *name*. We match the dominant name to its grounded ID; failing that, take the
    first grounded assay; failing that (no assays), return ``('unknown', name)``.
    """
    assays: list[dict[str, str]] = ontology.get("assays", [])
    dominant = ontology.get("modality", _UNKNOWN_ASSAY)
    for term in assays:
        if term.get("name") == dominant:
            return term.get("ontology_id", _UNKNOWN_ASSAY), term.get("name", dominant)
    if assays:
        first = assays[0]
        return first.get("ontology_id", _UNKNOWN_ASSAY), first.get("name", dominant)
    return _UNKNOWN_ASSAY, dominant
