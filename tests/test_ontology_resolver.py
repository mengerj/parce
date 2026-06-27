"""Offline unit tests for the OntologyResolver.

The OLS client is a deterministic fake; the cache is a real ResolutionCache on
tmp_path. No network IO.
"""

from __future__ import annotations

import pytest
import requests

from parce.models.graph_schema import MolecularLayer
from parce.ontology.base import ResolvedTerm
from parce.ontology.cache import ResolutionCache
from parce.ontology.ols import OlsTerm
from parce.ontology.registry import Facet
from parce.ontology.resolver import OntologyResolver


def _term(obo_id: str, label: str) -> OlsTerm:
    return OlsTerm(obo_id=obo_id, label=label, iri="", ontology_name="")


class _FakeClient:
    """Records calls; returns queued hits keyed by ontology (and optionally exact)."""

    def __init__(self, by_ontology=None, ancestors_terms=None):
        self._by_ontology = by_ontology or {}
        self._ancestors_terms = ancestors_terms or []
        self.search_calls: list[tuple[str, str, bool]] = []
        self.ancestors_calls: list[tuple[str, str]] = []

    def search(self, text, *, ontology, exact=False, rows=5):
        self.search_calls.append((text, ontology, exact))
        results = self._by_ontology.get(ontology, [])
        if isinstance(results, dict):
            return list(results.get(exact, []))
        return list(results)

    def ancestors(self, obo_id, *, ontology):
        self.ancestors_calls.append((obo_id, ontology))
        return list(self._ancestors_terms)


class _RaisingClient:
    def search(self, text, *, ontology, exact=False, rows=5):
        raise requests.ConnectionError("boom")

    def ancestors(self, obo_id, *, ontology):
        raise requests.ConnectionError("boom")


def _resolver(tmp_path, client, **kw) -> OntologyResolver:
    cache = ResolutionCache(tmp_path / "resolutions.json")
    return OntologyResolver(client=client, cache=cache, **kw)


_HUMAN = _term("NCBITaxon:9606", "Homo sapiens")


class TestResolveTerm:
    def test_resolves_and_caches(self, tmp_path):
        client = _FakeClient(by_ontology={"ncbitaxon": [_HUMAN]})
        resolver = _resolver(tmp_path, client)

        result = resolver.resolve_term("Homo sapiens", Facet.ORGANISM)
        assert result == ResolvedTerm("NCBITaxon:9606", "Homo sapiens")

        # Second call is served from cache: no further client search.
        again = resolver.resolve_term("Homo sapiens", Facet.ORGANISM)
        assert again == result
        assert len(client.search_calls) == 1

    def test_cache_hit_short_circuits_client(self, tmp_path):
        cache = ResolutionCache(tmp_path / "resolutions.json")
        cache.set("organism|homo sapiens", ResolvedTerm("NCBITaxon:9606", "Homo sapiens"))
        client = _FakeClient()  # would return nothing if consulted
        resolver = OntologyResolver(client=client, cache=cache)

        result = resolver.resolve_term("Homo sapiens", Facet.ORGANISM)
        assert result == ResolvedTerm("NCBITaxon:9606", "Homo sapiens")
        assert client.search_calls == []

    def test_exact_match_preferred(self, tmp_path):
        client = _FakeClient(by_ontology={"ncbitaxon": {True: [_HUMAN], False: []}})
        result = _resolver(tmp_path, client).resolve_term("Homo sapiens", Facet.ORGANISM)
        assert result == ResolvedTerm("NCBITaxon:9606", "Homo sapiens")
        # Stops after the exact hit — only one search.
        assert client.search_calls == [("Homo sapiens", "ncbitaxon", True)]

    def test_falls_back_to_fuzzy_when_no_exact(self, tmp_path):
        client = _FakeClient(by_ontology={"ncbitaxon": {True: [], False: [_HUMAN]}})
        result = _resolver(tmp_path, client).resolve_term("homo sapien", Facet.ORGANISM)
        assert result == ResolvedTerm("NCBITaxon:9606", "Homo sapiens")
        assert [c[2] for c in client.search_calls] == [True, False]

    def test_facet_fallback_ontology(self, tmp_path):
        # EFO has nothing; OBI provides the assay term. PSI-MS is never reached.
        obi_term = _term("OBI:0001271", "RNA-seq assay")
        client = _FakeClient(by_ontology={"efo": [], "obi": [obi_term]})
        result = _resolver(tmp_path, client).resolve_term("RNA-seq", Facet.ASSAY)
        assert result == ResolvedTerm("OBI:0001271", "RNA-seq assay")
        searched = {c[1] for c in client.search_calls}
        assert "efo" in searched and "obi" in searched
        assert "ms" not in searched

    def test_prefix_mismatch_is_ignored(self, tmp_path):
        # A hit whose CURIE is from the wrong ontology must not be accepted.
        wrong = _term("CL:0000084", "T cell")
        client = _FakeClient(by_ontology={"ncbitaxon": [wrong]})
        result = _resolver(tmp_path, client).resolve_term("Homo sapiens", Facet.ORGANISM)
        assert result is None

    def test_llm_fallback_used_when_deterministic_fails(self, tmp_path):
        calls: list[tuple[str, Facet]] = []

        def fallback(text, facet):
            calls.append((text, facet))
            return ResolvedTerm("NCBITaxon:9606", "Homo sapiens")

        client = _FakeClient(by_ontology={"ncbitaxon": []})
        resolver = _resolver(tmp_path, client, llm_fallback=fallback)

        result = resolver.resolve_term("hooman", Facet.ORGANISM)
        assert result == ResolvedTerm("NCBITaxon:9606", "Homo sapiens")
        assert calls == [("hooman", Facet.ORGANISM)]

    def test_no_fallback_returns_none_and_caches_negative(self, tmp_path):
        client = _FakeClient(by_ontology={"ncbitaxon": []})
        resolver = _resolver(tmp_path, client)

        assert resolver.resolve_term("hooman", Facet.ORGANISM) is None
        # Negative result cached: a second call does not re-query.
        assert resolver.resolve_term("hooman", Facet.ORGANISM) is None
        assert [c[2] for c in client.search_calls] == [True, False]

    @pytest.mark.parametrize("text", ["", "   ", "unknown", "UNKNOWN"])
    def test_blank_or_unknown_text_skips_client(self, tmp_path, text):
        client = _FakeClient(by_ontology={"ncbitaxon": [_HUMAN]})
        resolver = _resolver(tmp_path, client)
        assert resolver.resolve_term(text, Facet.ORGANISM) is None
        assert client.search_calls == []

    def test_search_error_degrades_to_none(self, tmp_path):
        resolver = _resolver(tmp_path, _RaisingClient())
        assert resolver.resolve_term("Homo sapiens", Facet.ORGANISM) is None


class TestMolecularLayer:
    def test_derives_from_ancestors(self, tmp_path):
        ancestors = [_term("EFO:0001457", "RNA assay")]
        client = _FakeClient(ancestors_terms=ancestors)
        layer = _resolver(tmp_path, client).molecular_layer("EFO:0009922")
        assert layer is MolecularLayer.TRANSCRIPTOME
        assert client.ancestors_calls == [("EFO:0009922", "efo")]

    def test_uses_assay_label_when_term_is_its_own_anchor(self, tmp_path):
        # Some assays (e.g. ATAC-seq) carry the layer signal only in their own
        # label; their EFO ancestors collapse to a generic "DNA assay". The label
        # must be consulted even when no ancestor matches.
        client = _FakeClient(ancestors_terms=[])  # no ancestors returned
        layer = _resolver(tmp_path, client).molecular_layer("EFO:0007045", assay_label="ATAC-seq")
        assert layer is MolecularLayer.EPIGENOME

    def test_unmatched_lineage_is_unknown(self, tmp_path):
        client = _FakeClient(ancestors_terms=[_term("EFO:0000001", "experimental factor")])
        assert _resolver(tmp_path, client).molecular_layer("EFO:0009922") is MolecularLayer.UNKNOWN

    def test_ancestor_error_degrades_to_unknown(self, tmp_path):
        resolver = _resolver(tmp_path, _RaisingClient())
        assert resolver.molecular_layer("EFO:0009922") is MolecularLayer.UNKNOWN
