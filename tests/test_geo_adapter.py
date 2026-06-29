"""Unit tests for the GEO source adapter and its SOFT parser.

All GEO network IO is mocked — these tests stay offline. The SOFT fixture mirrors
the real ``form=text&view=quick`` layout (a ``^SERIES`` block, a ``^PLATFORM``
block to be ignored, then ``^SAMPLE`` blocks).
"""

from __future__ import annotations

from unittest.mock import patch

from parce.models.raw_record import RawRecord
from parce.sources.base import SourceAdapter
from parce.sources.geo import GeoAdapter, _parse_soft

# A compact but realistic SOFT document: 2 samples, repeated summary/type keys,
# a PLATFORM block whose !Platform_* keys must not leak into the series fields.
_SOFT = """^SERIES = GSE99999
!Series_title = Smoking and lung adenocarcinoma
!Series_geo_accession = GSE99999
!Series_summary = We profiled tumor and normal lung tissue.
!Series_summary = Keywords: comparative genomics
!Series_overall_design = 2 tumor and 2 normal samples from 2 subjects.
!Series_type = Expression profiling by array
!Series_pubmed_id = 18297132
!Series_sample_id = GSM000001
!Series_sample_id = GSM000002
^PLATFORM = GPL96
!Platform_title = Affymetrix HG-U133A
!Platform_organism = Homo sapiens
^SAMPLE = GSM000001
!Sample_title = Lung Tumor A
!Sample_geo_accession = GSM000001
!Sample_type = RNA
!Sample_source_name_ch1 = Adenocarcinoma of the Lung
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = gender: Male
!Sample_characteristics_ch1 = tissue: tumor
!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM000001/suppl/GSM000001.CEL.gz
^SAMPLE = GSM000002
!Sample_title = Lung Normal A
!Sample_geo_accession = GSM000002
!Sample_type = RNA
!Sample_source_name_ch1 = Noninvolved Lung
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = gender: Female
!Sample_characteristics_ch1 = tissue: normal
!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM000002/suppl/GSM000002.CEL.gz
"""


class TestParseSoft:
    def test_series_single_and_multi_fields(self):
        series, _ = _parse_soft(_SOFT)
        assert series["title"] == "Smoking and lung adenocarcinoma"
        assert series["geo_accession"] == "GSE99999"
        assert series["overall_design"] == "2 tumor and 2 normal samples from 2 subjects."
        # Repeated keys collect into lists.
        assert series["summary"] == [
            "We profiled tumor and normal lung tissue.",
            "Keywords: comparative genomics",
        ]
        assert series["type"] == ["Expression profiling by array"]
        assert series["pubmed_id"] == ["18297132"]

    def test_platform_block_does_not_pollute_series(self):
        series, _ = _parse_soft(_SOFT)
        # !Platform_organism must not become a series/sample field.
        assert "organism" not in series

    def test_samples_parsed_with_characteristics(self):
        _, samples = _parse_soft(_SOFT)
        assert [s["sample_id"] for s in samples] == ["GSM000001", "GSM000002"]

        first = samples[0]
        assert first["title"] == "Lung Tumor A"
        assert first["source_name"] == "Adenocarcinoma of the Lung"
        assert first["organism"] == "Homo sapiens"
        assert first["characteristics"] == ["gender: Male", "tissue: tumor"]
        assert first["supplementary_file"].endswith("GSM000001.CEL.gz")

    def test_characteristics_kept_verbatim(self):
        """The adapter must not interpret characteristics — they pass through raw."""
        _, samples = _parse_soft(_SOFT)
        assert samples[1]["characteristics"] == ["gender: Female", "tissue: normal"]

    def test_handles_no_space_around_equals(self):
        soft = "^SAMPLE = GSM1\n!Sample_geo_accession=GSM1\n!Sample_characteristics_ch1=stage:IIB\n"
        _, samples = _parse_soft(soft)
        assert samples[0]["sample_id"] == "GSM1"
        assert samples[0]["characteristics"] == ["stage:IIB"]


class TestGeoAdapterDiscover:
    def test_discover_identity_on_accession(self):
        assert GeoAdapter().discover("GSE99999") == ["GSE99999"]

    def test_discover_uppercases_and_strips(self):
        assert GeoAdapter().discover("  gse123 ") == ["GSE123"]

    def test_discover_rejects_non_accession(self):
        assert GeoAdapter().discover("lung cancer") == []


class TestGeoAdapterFetch:
    def test_fetch_builds_raw_record(self):
        with patch.object(GeoAdapter, "_fetch_soft", return_value=_SOFT):
            record = GeoAdapter().fetch("GSE99999")

        assert isinstance(record, RawRecord)
        assert record.source == "GEO"
        assert record.study_id == "GSE99999"
        assert record.title == "Smoking and lung adenocarcinoma"
        assert len(record.payload["samples"]) == 2
        assert record.payload["truncated"] is False
        assert record.payload["series"]["type"] == ["Expression profiling by array"]

    def test_fetch_uppercases_accession(self):
        with patch.object(GeoAdapter, "_fetch_soft", return_value=_SOFT):
            record = GeoAdapter().fetch("gse99999")
        assert record.study_id == "GSE99999"

    def test_fetch_truncates_to_max_samples(self):
        with patch.object(GeoAdapter, "_fetch_soft", return_value=_SOFT):
            record = GeoAdapter().fetch("GSE99999", max_samples=1)
        assert len(record.payload["samples"]) == 1
        assert record.payload["truncated"] is True
        assert record.payload["samples"][0]["sample_id"] == "GSM000001"

    def test_fetch_passes_courtesy_params(self):
        captured: dict[str, object] = {}

        class _Resp:
            text = _SOFT

            def raise_for_status(self) -> None:
                return None

        def _fake_get(url, params, timeout):
            captured["url"] = url
            captured["params"] = params
            return _Resp()

        with patch("parce.sources.geo.requests.get", side_effect=_fake_get):
            GeoAdapter(email="me@example.com", api_key="KEY").fetch("GSE99999")

        params = captured["params"]
        assert params["acc"] == "GSE99999"
        assert params["targ"] == "all"
        assert params["email"] == "me@example.com"
        assert params["api_key"] == "KEY"


class TestProtocolConformance:
    def test_adapter_satisfies_source_adapter(self):
        assert isinstance(GeoAdapter(), SourceAdapter)
