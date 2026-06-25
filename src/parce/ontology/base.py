"""Value types and the resolver contract for the shared ontology stage.

Kept dependency-light (only the registry) so both the cache and the normalizers
can import :class:`ResolvedTerm` / :class:`TermResolver` without pulling in the
OLS client or ``requests``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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
