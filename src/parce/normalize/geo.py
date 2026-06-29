"""Agent-backed normalizer: a GEO ``RawRecord`` → canonical KG nodes.

GEO is the project's first *unstructured* source, so this is the first normalizer
with an LLM in its path. The division of labour is deliberate and follows the
"could a deterministic step do this?" rule (CLAUDE.md):

* **Deterministic** — fields GEO already ships structured are read straight from
  the record: each sample's ``organism`` (``!Sample_organism_ch1``) and its raw
  data URI (``!Sample_supplementary_file``). The set of samples (one ``SampleNode``
  per real ``GSM``) is the record's, never the LLM's, so a hallucinated or dropped
  sample cannot change the graph's shape.
* **LLM (structured extraction only)** — the genuinely free-text job: turning the
  ``!Sample_characteristics_ch1`` lines into the canonical **design** covariates
  (``condition``/``perturbation``/``timepoint``/``subject``) and reading the
  study-level ``assay``/``tissue``/``disease`` out of the series prose. The agent
  is constrained by ``response_format`` to the :class:`GeoExtraction` schema — it
  cannot emit prose, and the schema has **no field for any data-inferred
  annotation** (cell type, clusters), so leakage is structurally impossible
  (docs/ARCHITECTURE.md §1).
* **Shared ontology stage** — every extracted free-text facet is grounded through
  the same :class:`~parce.ontology.base.OntologyService` the CELLxGENE path uses
  (organism→NCBITaxon, assay→EFO + ``molecular_layer``, tissue→UBERON,
  disease→MONDO), so GEO studies land on the *same* IDs and link to CELLxGENE
  through shared entity nodes.

GEO has no distinct dataset artifact (unlike CELLxGENE's Census datasets): the
series *is* the study and its data lives in per-sample supplementary files. So no
``DatasetNode`` is emitted; ``assay``/``molecular_layer`` live on the ``StudyNode``
and the design-context + ``HAS_SAMPLE`` edges originate at the study. Cross-source
linking is unaffected — it flows through shared entity ``ontology_id`` targets,
not the originating node (docs/ARCHITECTURE.md §4).
"""

from __future__ import annotations

import logging
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from parce.agent.base import StructuredExtractor
from parce.models.graph_schema import (
    BiologicalEntityNode,
    EntityType,
    GraphEdge,
    KnowledgeGraphOutput,
    MolecularLayer,
    SampleNode,
    StudyNode,
)
from parce.models.raw_record import RawRecord
from parce.ontology import Facet, OntologyResolver, OntologyService

logger = logging.getLogger(__name__)

_UNKNOWN = "unknown"


# -- the agent's response_format schema ---------------------------------------
# These are agent IO models, not canonical KG nodes, so they use ``extra="ignore"``
# (be lenient with the model's output) rather than the KG models' ``extra="forbid"``.
# They carry only experiment-*design* fields — there is deliberately no field for a
# data-inferred annotation, so the schema itself forbids leakage.


class SampleExtraction(BaseModel):
    """Per-sample design covariates the LLM reads from ``characteristics_ch1``."""

    model_config = ConfigDict(extra="ignore")

    sample_id: str = Field(..., description="The GEO sample accession (GSM...), echoed verbatim.")
    condition: str | None = Field(
        default=None, description="Experimental condition as designed (e.g. 'tumor', 'control')."
    )
    perturbation: str | None = Field(
        default=None, description="Designed perturbation: a drug, dose, genetic knockout, etc."
    )
    timepoint: str | None = Field(
        default=None, description="Designed sampling timepoint (e.g. '0h', 'day 7')."
    )
    subject: str | None = Field(
        default=None, description="Subject/donor/patient/replicate identifier."
    )


class GeoExtraction(BaseModel):
    """Structured view of one GEO series the extraction agent must return."""

    model_config = ConfigDict(extra="ignore")

    assay: str | None = Field(
        default=None,
        description="The assay/technology in plain words (e.g. 'RNA-seq', 'microarray').",
    )
    tissue: str | None = Field(
        default=None, description="The tissue/anatomical source studied (e.g. 'lung')."
    )
    disease: str | None = Field(
        default=None, description="The disease/condition studied (e.g. 'lung adenocarcinoma')."
    )
    samples: list[SampleExtraction] = Field(default_factory=list)


GEO_EXTRACTION_INSTRUCTIONS = (
    "You extract experiment-DESIGN metadata from a GEO series into the given schema. "
    "Use only what the text states about how the experiment was DESIGNED: the assay/"
    "technology, the tissue/anatomy sampled, the disease/condition studied, and per-"
    "sample condition, perturbation (drug/dose/genetic), timepoint, and subject/donor. "
    "NEVER infer or output cell types, cluster labels, or anything derived from the "
    "measured data — only design variables. Echo each sample_id (GSM...) exactly. "
    "Leave any field null when the text does not state it; do not guess."
)


def _serialise_for_agent(record: RawRecord) -> str:
    """Render the record as the plain-text prompt content the agent reads."""
    series = record.payload.get("series", {})
    lines: list[str] = [
        f"GEO Series: {record.study_id}",
        f"Title: {record.title}",
        f"Type: {'; '.join(series.get('type', [])) or _UNKNOWN}",
        f"Summary: {' '.join(series.get('summary', [])) or _UNKNOWN}",
        f"Overall design: {series.get('overall_design', _UNKNOWN)}",
        "",
        "Samples:",
    ]
    for s in record.payload.get("samples", []):
        chars = "; ".join(s.get("characteristics", [])) or "(none)"
        lines.append(
            f"- {s.get('sample_id', _UNKNOWN)} | title: {s.get('title', '')} | "
            f"source: {s.get('source_name', '')} | characteristics: {chars}"
        )
    return "\n".join(lines)


class GeoNormalizer:
    """:class:`~parce.normalize.base.Normalizer` for GEO ``RawRecord``s (LLM-backed).

    Requires a :class:`~parce.agent.base.StructuredExtractor` (the LLM seam — inject
    a fake to test offline). The :class:`~parce.ontology.base.OntologyService`
    defaults to a real :class:`~parce.ontology.resolver.OntologyResolver`; inject a
    fake to keep grounding offline too.
    """

    def __init__(
        self, extractor: StructuredExtractor, *, resolver: OntologyService | None = None
    ) -> None:
        self._extractor = extractor
        self._resolver: OntologyService = resolver if resolver is not None else OntologyResolver()

    def normalize(self, record: RawRecord) -> KnowledgeGraphOutput:
        """Assemble the canonical single-study subgraph for one GEO series."""
        study_id = record.study_id
        raw_samples = record.payload.get("samples", [])

        extraction = self._extract(record)
        covariates = {s.sample_id: s for s in extraction.samples}

        entity_registry: dict[str, BiologicalEntityNode] = {}
        edges: list[GraphEdge] = []
        samples: list[SampleNode] = []

        # -- samples: structured fields from the record, design covariates from
        #    the LLM. The record's sample set is authoritative.
        organism_counts: Counter[str] = Counter()
        for raw in raw_samples:
            sample_id = raw.get("sample_id")
            if not sample_id:
                continue
            organism = raw.get("organism") or None
            if organism:
                organism_counts[organism] += 1

            cov = covariates.get(sample_id)
            samples.append(
                SampleNode(
                    sample_id=sample_id,
                    data_uri=raw.get("supplementary_file") or None,
                    organism=organism,
                    condition=cov.condition if cov else None,
                    perturbation=cov.perturbation if cov else None,
                    timepoint=cov.timepoint if cov else None,
                    subject=cov.subject if cov else None,
                )
            )
            edges.append(
                GraphEdge(source_id=study_id, target_id=sample_id, relation_type="HAS_SAMPLE")
            )

        # -- study-level assay → EFO term + molecular_layer.
        assay_id, assay_label = self._ground(extraction.assay, Facet.ASSAY)
        layer = self._molecular_layer(assay_id, assay_label)
        if assay_id != _UNKNOWN:
            self._register(
                entity_registry,
                EntityType.ASSAY,
                assay_id,
                assay_label,
                study_id,
                "MEASURED_WITH",
                edges,
            )

        # -- study-level tissue / disease.
        tissue_id, tissue_label = self._ground(extraction.tissue, Facet.TISSUE)
        if tissue_id != _UNKNOWN:
            self._register(
                entity_registry,
                EntityType.TISSUE,
                tissue_id,
                tissue_label,
                study_id,
                "HAS_TISSUE",
                edges,
            )
        disease_id, disease_label = self._ground(extraction.disease, Facet.DISEASE)
        if disease_id != _UNKNOWN:
            self._register(
                entity_registry,
                EntityType.DISEASE,
                disease_id,
                disease_label,
                study_id,
                "HAS_CONDITION",
                edges,
            )

        # -- dominant organism → Species entity + STUDIES edge.
        if organism_counts:
            dominant_organism = organism_counts.most_common(1)[0][0]
            species = self._resolver.resolve_term(dominant_organism, Facet.ORGANISM)
            if species is not None:
                self._register(
                    entity_registry,
                    EntityType.SPECIES,
                    species.ontology_id,
                    species.name,
                    study_id,
                    "STUDIES",
                    edges,
                )

        study = StudyNode(
            study_id=study_id,
            title=record.title,
            source=record.source,
            assay=assay_id,
            molecular_layer=layer,
        )

        kg = KnowledgeGraphOutput(
            studies=[study],
            datasets=[],
            samples=samples,
            biological_entities=list(entity_registry.values()),
            edges=edges,
        )
        logger.info(
            "Normalized GEO study=%s: samples=%d entities=%d edges=%d assay=%s layer=%s",
            study_id,
            len(kg.samples),
            len(kg.biological_entities),
            len(kg.edges),
            assay_id,
            layer,
        )
        return kg

    # -- helpers ---------------------------------------------------------------
    def _extract(self, record: RawRecord) -> GeoExtraction:
        """Run the extraction agent; degrade to an empty extraction on failure."""
        try:
            return self._extractor.extract(
                GEO_EXTRACTION_INSTRUCTIONS, _serialise_for_agent(record), GeoExtraction
            )
        except Exception as exc:
            logger.warning("GEO extraction failed for %s: %s", record.study_id, exc)
            return GeoExtraction()

    def _ground(self, text: str | None, facet: Facet) -> tuple[str, str]:
        """Ground free text to ``(ontology_id, label)``; ``('unknown', text)`` if not."""
        if not text or not text.strip():
            return _UNKNOWN, text or _UNKNOWN
        term = self._resolver.resolve_term(text, facet)
        if term is None:
            return _UNKNOWN, text
        return term.ontology_id, term.name

    def _molecular_layer(self, assay_id: str, assay_label: str) -> MolecularLayer:
        """Derive the molecular layer; only EFO assay terms carry a walkable lineage."""
        if assay_id.startswith("EFO:"):
            return self._resolver.molecular_layer(assay_id, assay_label=assay_label)
        return MolecularLayer.UNKNOWN

    @staticmethod
    def _register(
        registry: dict[str, BiologicalEntityNode],
        entity_type: EntityType,
        ontology_id: str,
        name: str,
        source_id: str,
        relation: str,
        edges: list[GraphEdge],
    ) -> None:
        """Register an entity (deduped by ontology ID) and add its edge from source."""
        if ontology_id not in registry:
            registry[ontology_id] = BiologicalEntityNode(
                entity_type=entity_type, ontology_id=ontology_id, name=name
            )
        edges.append(GraphEdge(source_id=source_id, target_id=ontology_id, relation_type=relation))
