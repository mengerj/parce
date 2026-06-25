"""Facet → ontology registry: the single source of truth for *which* controlled
vocabulary annotates *which* experiment-design facet.

This pins **ontologies, never term IDs**. Specific EFO/MONDO/NCBITaxon/... IDs
are resolved and validated at runtime via OLS (see
:mod:`parce.ontology.resolver`); nothing here is a hardcoded resolution result.
See docs/ARCHITECTURE.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Facet(StrEnum):
    """An experiment-*design* facet that binds to one designated ontology.

    Cell type is intentionally absent: it is a data-inferred annotation, not a
    design variable (see docs/ARCHITECTURE.md §1).
    """

    ASSAY = "assay"
    TISSUE = "tissue"
    DISEASE = "disease"
    ORGANISM = "organism"
    PERTURBATION = "perturbation"
    DATA_FORMAT = "data_format"


@dataclass(frozen=True, slots=True)
class Ontology:
    """A controlled vocabulary used to ground one or more facets.

    ``ols_id`` is the OLS4 ontology slug (lowercase) used in API queries;
    ``prefix`` is the CURIE prefix its term IDs carry (e.g. ``NCBITaxon`` in
    ``NCBITaxon:9606``).
    """

    ols_id: str
    prefix: str
    title: str


@dataclass(frozen=True, slots=True)
class FacetBinding:
    """How a facet binds to ontologies: a primary plus ordered fallbacks.

    Resolution tries ``primary`` first, then each fallback in order — e.g. an
    assay missing from EFO is sought in OBI, and MS-specific terms in PSI-MS.
    """

    primary: Ontology
    fallbacks: tuple[Ontology, ...] = field(default_factory=tuple)

    def ontologies(self) -> tuple[Ontology, ...]:
        """The primary followed by its fallbacks, in resolution order."""
        return (self.primary, *self.fallbacks)


# The seven ontologies the registry pins (see docs/ARCHITECTURE.md §5).
EFO = Ontology("efo", "EFO", "Experimental Factor Ontology")
OBI = Ontology("obi", "OBI", "Ontology for Biomedical Investigations")
PSI_MS = Ontology("ms", "MS", "PSI Mass Spectrometry CV")
UBERON = Ontology("uberon", "UBERON", "Uberon anatomy ontology")
MONDO = Ontology("mondo", "MONDO", "Mondo Disease Ontology")
NCBITAXON = Ontology("ncbitaxon", "NCBITaxon", "NCBI organismal taxonomy")
CHEBI = Ontology("chebi", "CHEBI", "Chemical Entities of Biological Interest")
EDAM = Ontology("edam", "EDAM", "EDAM data and format ontology")

# The registry itself. EFO is the assay anchor; OBI covers upper-level assays it
# lacks and PSI-MS the mass-spectrometry specifics (matching SDRF-Proteomics).
FACET_ONTOLOGY: dict[Facet, FacetBinding] = {
    Facet.ASSAY: FacetBinding(EFO, (OBI, PSI_MS)),
    Facet.TISSUE: FacetBinding(UBERON),
    Facet.DISEASE: FacetBinding(MONDO),
    Facet.ORGANISM: FacetBinding(NCBITAXON),
    Facet.PERTURBATION: FacetBinding(CHEBI),
    Facet.DATA_FORMAT: FacetBinding(EDAM),
}
