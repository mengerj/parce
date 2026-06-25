"""The shared ontology-resolution stage.

:class:`OntologyResolver` grounds free-text experiment-design strings to ontology
term IDs and derives the coarse ``molecular_layer`` for an assay. It is the one
place every source's free text lands on the *same* IDs — the precondition for
cross-source linking (docs/ARCHITECTURE.md §3, §5).

Resolution order, deterministic-first:

1. on-disk cache (negative results included);
2. OLS4 search across the facet's registered ontologies (primary, then
   fallbacks), exact match preferred;
3. an optional **LLM fallback** for strings the deterministic resolvers can't
   map — supplied as a plain callable so this package never depends on
   ``parce.agent``/Azure. It defaults to ``None`` (no fallback) and is wired up
   with the extraction agent in a later PR.

Network/parse failures degrade gracefully to "unresolved" (logged) rather than
crashing an ingest; the shared retry helper has already exhausted transient
retries by then.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from parce.models.graph_schema import MolecularLayer
from parce.ontology.base import ResolvedTerm
from parce.ontology.cache import ResolutionCache
from parce.ontology.layers import derive_molecular_layer
from parce.ontology.ols import OlsClient, OlsTerm
from parce.ontology.registry import FACET_ONTOLOGY, Facet, Ontology

logger = logging.getLogger(__name__)

# Project-root-relative default cache location. ``data/`` is gitignored.
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "ontology_cache"

LlmFallback = Callable[[str, Facet], ResolvedTerm | None]


class OntologyResolver:
    """Grounds free text to ontology terms; deterministic OLS-first.

    All collaborators are injectable so the resolver can be driven entirely
    offline in unit tests. The default :class:`~parce.ontology.cache.ResolutionCache`
    is constructed lazily (on first use) so merely instantiating the resolver
    touches neither disk nor network.
    """

    def __init__(
        self,
        *,
        client: OlsClient | None = None,
        cache: ResolutionCache | None = None,
        cache_dir: Path | str = _DEFAULT_CACHE_DIR,
        llm_fallback: LlmFallback | None = None,
    ) -> None:
        self._client = client if client is not None else OlsClient()
        self._cache = cache
        self._cache_dir = Path(cache_dir)
        self._llm_fallback = llm_fallback

    # -- cache (lazy) ----------------------------------------------------
    def _get_cache(self) -> ResolutionCache:
        # Built lazily so constructing the resolver touches neither disk nor net.
        if self._cache is None:
            self._cache = ResolutionCache(self._cache_dir / "resolutions.json")
        return self._cache

    @staticmethod
    def _cache_key(text: str, facet: Facet) -> str:
        return f"{facet.value}|{text.strip().lower()}"

    # -- term resolution -------------------------------------------------
    def resolve_term(self, text: str, facet: Facet) -> ResolvedTerm | None:
        """Ground ``text`` to a term for ``facet``; ``None`` if unresolved.

        Caches every outcome (including ``None``) so the same string is queried
        at most once per cache lifetime.
        """
        clean = text.strip()
        if not clean or clean.lower() == "unknown":
            return None

        cache = self._get_cache()
        key = self._cache_key(clean, facet)
        present, cached = cache.get(key)
        if present:
            return cached

        result = self._resolve_uncached(clean, facet)
        cache.set(key, result)
        return result

    def _resolve_uncached(self, text: str, facet: Facet) -> ResolvedTerm | None:
        for ontology in FACET_ONTOLOGY[facet].ontologies():
            term = self._search_one(text, ontology)
            if term is not None:
                return term
        if self._llm_fallback is not None:
            logger.info("Deterministic resolution failed for %r (%s); trying LLM", text, facet)
            return self._llm_fallback(text, facet)
        logger.warning("Unresolved term %r for facet %s", text, facet)
        return None

    def _search_one(self, text: str, ontology: Ontology) -> ResolvedTerm | None:
        """Exact match first, then the best fuzzy hit, within one ontology."""
        prefix = f"{ontology.prefix}:"
        for exact in (True, False):
            try:
                hits = self._client.search(text, ontology=ontology.ols_id, exact=exact)
            except Exception as exc:  # network/HTTP/parse — treat as a miss here
                logger.warning(
                    "OLS search failed for %r in %s (exact=%s): %s",
                    text,
                    ontology.ols_id,
                    exact,
                    exc,
                )
                return None
            for hit in hits:
                if hit.obo_id.startswith(prefix):
                    return ResolvedTerm(ontology_id=hit.obo_id, name=hit.label or text)
        return None

    # -- molecular layer -------------------------------------------------
    def molecular_layer(self, assay_id: str, *, assay_label: str | None = None) -> MolecularLayer:
        """Derive the coarse molecular layer of an EFO ``assay_id``.

        Walks the term's ``is-a`` ancestors via OLS and matches their labels
        against the pinned anchor set (see :mod:`parce.ontology.layers`). Passing
        the assay's own ``assay_label`` lets a term that is itself an anchor be
        classified without relying on the ancestor list including self. Falls
        back to :attr:`MolecularLayer.UNKNOWN` on any resolution failure.
        """
        try:
            ancestors: list[OlsTerm] = self._client.ancestors(assay_id, ontology="efo")
        except Exception as exc:
            logger.warning("Ancestor walk failed for assay %s: %s", assay_id, exc)
            return MolecularLayer.UNKNOWN

        labels = [a.label for a in ancestors]
        if assay_label:
            labels.append(assay_label)
        return derive_molecular_layer(labels)
