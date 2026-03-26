"""Basic validation tests for the Pydantic narrative models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parce.models.narrative import DataURI, ExperimentNarrative, SampleRecord


class TestDataURI:
    def test_valid(self):
        uri = DataURI(uri="https://example.com/file.fastq.gz", file_type="FASTQ")
        assert uri.uri == "https://example.com/file.fastq.gz"
        assert uri.description is None

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DataURI(uri="https://example.com/f.bam", file_type="BAM", extra_field="oops")


class TestSampleRecord:
    def test_minimal(self):
        sample = SampleRecord(sample_id="GSM0001", organism="Mus musculus")
        assert sample.cell_type is None
        assert sample.data_uris == []

    def test_full(self):
        sample = SampleRecord(
            sample_id="GSM0002",
            organism="Homo sapiens",
            strain=None,
            cell_type="CD8+ T cell",
            tissue="spleen",
            condition="knockout",
            knockout_gene="Pdcd1",
            data_uris=[
                DataURI(uri="https://example.com/SRR001.fastq", file_type="FASTQ"),
            ],
        )
        assert len(sample.data_uris) == 1
        assert sample.knockout_gene == "Pdcd1"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            SampleRecord(sample_id="GSM0003", organism="Mus musculus", bogus=True)


class TestExperimentNarrative:
    def test_minimal(self):
        narrative = ExperimentNarrative(
            accession="GSE000001",
            title="Test experiment",
            summary="A short summary.",
        )
        assert narrative.samples == []
        assert narrative.platform is None

    def test_roundtrip_json(self):
        narrative = ExperimentNarrative(
            accession="GSE164378",
            title="T-cell profiling",
            summary="Profiled T cells under PD-1 blockade.",
            platform="Illumina NovaSeq 6000",
            samples=[
                SampleRecord(
                    sample_id="GSM5008101",
                    organism="Homo sapiens",
                    cell_type="CD8+ T cell",
                    tissue="peripheral blood",
                    condition="pre-treatment",
                    data_uris=[
                        DataURI(
                            uri="https://example.com/SRR13568101",
                            file_type="FASTQ",
                        )
                    ],
                )
            ],
        )
        json_str = narrative.model_dump_json()
        restored = ExperimentNarrative.model_validate_json(json_str)
        assert restored == narrative

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ExperimentNarrative(
                accession="GSE000002",
                title="Bad",
                summary="Nope",
                unexpected="field",
            )
