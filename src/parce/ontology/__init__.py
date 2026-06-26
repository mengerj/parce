"""Shared ontology-resolution stage: free text → ontology term IDs.

Every source's free-text design fields land here so they resolve to the *same*
IDs, which is what lets studies link across sources (docs/ARCHITECTURE.md §5).
The public surface:

* :class:`Facet` / :data:`FACET_ONTOLOGY` — which ontology grounds which facet;
* :class:`OntologyResolver` — OLS-first resolver with on-disk cache and an
  optional LLM fallback hook;
* :class:`ResolvedTerm` / :class:`TermResolver` / :class:`OntologyService` — the
  value type and the contracts normalizers depend on.
"""

from __future__ import annotations

from parce.ontology.base import OntologyService, ResolvedTerm, TermResolver
from parce.ontology.cache import ResolutionCache
from parce.ontology.layers import derive_molecular_layer
from parce.ontology.ols import OlsClient, OlsTerm
from parce.ontology.registry import FACET_ONTOLOGY, Facet, FacetBinding, Ontology
from parce.ontology.resolver import OntologyResolver

__all__ = [
    "FACET_ONTOLOGY",
    "Facet",
    "FacetBinding",
    "OlsClient",
    "OlsTerm",
    "Ontology",
    "OntologyResolver",
    "OntologyService",
    "ResolutionCache",
    "ResolvedTerm",
    "TermResolver",
    "derive_molecular_layer",
]
