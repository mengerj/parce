"""Unit tests for the on-disk resolution cache (uses tmp_path, no network)."""

from __future__ import annotations

from parce.ontology.base import ResolvedTerm
from parce.ontology.cache import ResolutionCache


class TestResolutionCache:
    def test_miss_then_set_then_hit(self, tmp_path):
        cache = ResolutionCache(tmp_path / "c.json")
        present, value = cache.get("organism|homo sapiens")
        assert present is False
        assert value is None

        term = ResolvedTerm("NCBITaxon:9606", "Homo sapiens")
        cache.set("organism|homo sapiens", term)

        present, value = cache.get("organism|homo sapiens")
        assert present is True
        assert value == term

    def test_negative_result_is_distinct_from_miss(self, tmp_path):
        cache = ResolutionCache(tmp_path / "c.json")
        cache.set("organism|martian", None)

        present, value = cache.get("organism|martian")
        assert present is True  # cached...
        assert value is None  # ...as a negative result

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "c.json"
        term = ResolvedTerm("MONDO:0008903", "lung cancer")
        ResolutionCache(path).set("disease|lung cancer", term)

        reloaded = ResolutionCache(path)
        present, value = reloaded.get("disease|lung cancer")
        assert present is True
        assert value == term

    def test_negative_persists_across_instances(self, tmp_path):
        path = tmp_path / "c.json"
        ResolutionCache(path).set("organism|martian", None)

        present, value = ResolutionCache(path).get("organism|martian")
        assert present is True
        assert value is None

    def test_creates_parent_dir_on_write(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "c.json"
        ResolutionCache(path).set("k", None)
        assert path.exists()

    def test_corrupt_file_is_ignored(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text("{not valid json", encoding="utf-8")
        cache = ResolutionCache(path)  # must not raise
        present, _ = cache.get("anything")
        assert present is False
