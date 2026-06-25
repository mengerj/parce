"""Offline unit tests for the OLS4 REST client.

No network: a fake HTTP getter records calls and returns canned JSON. The double
URL-encoding and CURIE→IRI conventions are asserted against the recorded URL.
"""

from __future__ import annotations

import pytest
import requests

from parce.ontology.ols import OlsClient, obo_id_to_iri


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            resp = requests.Response()
            resp.status_code = self.status_code
            err.response = resp
            raise err


class _FakeHttp:
    """Records the last GET and replays a queued response."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response


class TestOboIdToIri:
    def test_efo_namespace(self):
        assert obo_id_to_iri("EFO:0009922") == "http://www.ebi.ac.uk/efo/EFO_0009922"

    def test_generic_obo_purl(self):
        assert obo_id_to_iri("UBERON:0000178") == "http://purl.obolibrary.org/obo/UBERON_0000178"
        assert obo_id_to_iri("NCBITaxon:9606") == "http://purl.obolibrary.org/obo/NCBITaxon_9606"

    def test_non_curie_returns_none(self):
        assert obo_id_to_iri("not-a-curie") is None


class TestSearch:
    def test_parses_docs_and_filters_missing_obo_id(self):
        payload = {
            "response": {
                "docs": [
                    {
                        "obo_id": "NCBITaxon:9606",
                        "label": "Homo sapiens",
                        "iri": "http://purl.obolibrary.org/obo/NCBITaxon_9606",
                        "ontology_name": "ncbitaxon",
                    },
                    {"label": "no obo id here"},  # dropped
                ]
            }
        }
        http = _FakeHttp(_FakeResponse(payload))
        client = OlsClient(http=http)

        terms = client.search("Homo sapiens", ontology="ncbitaxon", exact=True)

        assert len(terms) == 1
        assert terms[0].obo_id == "NCBITaxon:9606"
        assert terms[0].label == "Homo sapiens"

        url, kwargs = http.calls[0]
        assert url.endswith("/search")
        params = kwargs["params"]
        assert params["q"] == "Homo sapiens"
        assert params["ontology"] == "ncbitaxon"
        assert params["exact"] == "true"
        assert params["type"] == "class"

    def test_empty_response(self):
        http = _FakeHttp(_FakeResponse({"response": {"docs": []}}))
        assert OlsClient(http=http).search("nonsense", ontology="efo") == []


class TestAncestors:
    def test_double_encodes_iri_and_parses_terms(self):
        payload = {
            "_embedded": {
                "terms": [
                    {"obo_id": "EFO:0002772", "label": "assay by molecule"},
                    {"obo_id": "EFO:0001457", "label": "RNA assay"},
                    {"label": "skipped, no obo_id"},
                ]
            }
        }
        http = _FakeHttp(_FakeResponse(payload))
        client = OlsClient(http=http)

        terms = client.ancestors("EFO:0009922", ontology="efo")

        labels = [t.label for t in terms]
        assert labels == ["assay by molecule", "RNA assay"]

        url, _ = http.calls[0]
        # IRI is http://www.ebi.ac.uk/efo/EFO_0009922, double-URL-encoded:
        # ':' -> %3A -> %253A and '/' -> %2F -> %252F.
        assert "%253A" in url
        assert "%252F" in url
        assert url.endswith("/hierarchicalAncestors")

    def test_unmappable_curie_returns_empty_without_network(self):
        http = _FakeHttp(_FakeResponse({}))
        terms = OlsClient(http=http).ancestors("not-a-curie", ontology="efo")
        assert terms == []
        assert http.calls == []  # never hit the network


class TestErrorHandling:
    def test_non_transient_http_error_propagates(self):
        http = _FakeHttp(_FakeResponse({}, status_code=404))
        with pytest.raises(requests.HTTPError):
            OlsClient(http=http).search("x", ontology="efo")

    def test_transient_error_is_retried_then_raises(self, monkeypatch):
        # 503 is transient: with_retries retries (sleep patched) then re-raises.
        monkeypatch.setattr("parce.sources._retry.time.sleep", lambda _s: None)
        http = _FakeHttp(_FakeResponse({}, status_code=503))
        client = OlsClient(http=http, max_attempts=3)
        with pytest.raises(requests.HTTPError):
            client.search("x", ontology="efo")
        assert len(http.calls) == 3  # all attempts made
