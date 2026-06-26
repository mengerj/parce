"""Value types and the resolver contracts for the shared ontology stage.

Kept dependency-light (only the registry and the canonical ``MolecularLayer``
enum) so both the cache and the normalizers can import :class:`ResolvedTerm` /
:class:`TermResolver` / :class:`OntologyService` without pulling in the OLS
client or ``requests``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parce.models.graph_schema import MolecularLayer
from parce.ontology.registry import Facet


@dataclass(frozen=True, slots=True)
class ResolvedTerm:
    """A free-text string grounded to one ontology term.

    ``ontology_id`` is a CURIE (e.g. ``NCBITaxon:9606``); ``name`` is the term's
    canonical label as returned by the ontology service.
    """

    ontology_id: str
    name: str


@runtime_checkable
class TermResolver(Protocol):
    """Grounds a free-text term for a given facet, or returns ``None``.

    Normalizers depend on this narrow contract rather than the concrete
    :class:`~parce.ontology.resolver.OntologyResolver`, so unit tests can inject a
    deterministic fake and stay offline.
    """

    def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
        """Return the grounded term for ``text`` under ``facet``, else ``None``."""
        ...


@runtime_checkable
class OntologyService(TermResolver, Protocol):
    """A :class:`TermResolver` that also derives an assay's molecular layer.

    The fuller contract the CELLxGENE normalizer depends on: ground free text
    (organism) *and* classify an EFO ``assay`` term into a coarse
    :class:`~parce.models.graph_schema.MolecularLayer`. The concrete
    :class:`~parce.ontology.resolver.OntologyResolver` satisfies it; unit tests
    inject an offline fake implementing both methods.
    """

    def molecular_layer(self, assay_id: str, *, assay_label: str | None = None) -> MolecularLayer:
        """Return the coarse molecular layer for EFO ``assay_id``."""
        ...
