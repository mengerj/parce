"""Thin OLS4 (EBI Ontology Lookup Service) REST client.

Two operations the resolver needs, and nothing more:

* :meth:`OlsClient.search` — free text → candidate terms within one ontology
  (used to ground organism/tissue/disease/assay strings).
* :meth:`OlsClient.ancestors` — a term's ``is-a`` ancestors (used to walk an EFO
  assay term up to a ``molecular_layer`` anchor).

This is the only module in the ontology stage that performs network IO, so the
rest of the stage stays unit-testable offline. Requests are wrapped in the shared
:func:`parce.sources._retry.with_retries` helper (bounded retries, jittered
backoff on transient 429/5xx/network faults).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import quote

import requests

from parce.sources._retry import DEFAULT_MAX_ATTEMPTS, with_retries

logger = logging.getLogger(__name__)

DEFAULT_OLS_BASE_URL = "https://www.ebi.ac.uk/ols4/api"
_DEFAULT_TIMEOUT = 30


class _HttpGetter(Protocol):
    """The slice of ``requests`` / ``requests.Session`` the client relies on."""

    def get(self, url: str, **kwargs: Any) -> requests.Response: ...


@dataclass(frozen=True, slots=True)
class OlsTerm:
    """A single OLS term hit: its CURIE, label, IRI and owning ontology."""

    obo_id: str
    label: str
    iri: str
    ontology_name: str


def obo_id_to_iri(obo_id: str) -> str | None:
    """Best-effort CURIE → IRI for the ontologies the resolver walks.

    EFO terms use the ``ebi.ac.uk/efo`` namespace; the other OBO ontologies
    (UBERON, MONDO, CHEBI, NCBITaxon, OBI, PSI-MS, …) use the shared OBO PURL.
    Returns ``None`` for an unrecognised/non-CURIE id. EDAM has its own scheme
    but is never walked for ancestors, so it is intentionally not handled.
    """
    if ":" not in obo_id:
        return None
    prefix, local = obo_id.split(":", 1)
    if prefix == "EFO":
        return f"http://www.ebi.ac.uk/efo/EFO_{local}"
    return f"http://purl.obolibrary.org/obo/{prefix}_{local}"


class OlsClient:
    """Minimal OLS4 client; ``http`` is injectable so tests stay offline."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLS_BASE_URL,
        *,
        http: _HttpGetter | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # The ``requests`` module exposes a matching ``get``; cast for the type.
        self._http: _HttpGetter = http if http is not None else cast("_HttpGetter", requests)
        self._timeout = timeout
        self._max_attempts = max_attempts

    def _get_json(self, url: str, params: dict[str, Any], description: str) -> dict[str, Any]:
        def _do() -> requests.Response:
            resp = self._http.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp

        resp = with_retries(_do, max_attempts=self._max_attempts, description=description)
        data: dict[str, Any] = resp.json()
        return data

    def search(
        self, text: str, *, ontology: str, exact: bool = False, rows: int = 5
    ) -> list[OlsTerm]:
        """Search ``ontology`` for ``text``; return class hits (best first)."""
        params: dict[str, Any] = {
            "q": text,
            "ontology": ontology,
            "type": "class",
            "exact": str(exact).lower(),
            "rows": rows,
            "fieldList": "iri,label,obo_id,ontology_name",
        }
        data = self._get_json(
            f"{self._base_url}/search",
            params,
            description=f"OLS search q={text!r} ontology={ontology} exact={exact}",
        )
        docs = data.get("response", {}).get("docs", [])
        return [self._to_term(doc) for doc in docs if doc.get("obo_id")]

    def ancestors(self, obo_id: str, *, ontology: str) -> list[OlsTerm]:
        """Return the ``is-a`` (hierarchical) ancestors of ``obo_id``.

        Returns an empty list when the CURIE has no IRI mapping (see
        :func:`obo_id_to_iri`).
        """
        iri = obo_id_to_iri(obo_id)
        if iri is None:
            logger.warning("No IRI mapping for %s; cannot fetch ancestors", obo_id)
            return []
        # OLS requires the IRI double-URL-encoded in the path segment.
        encoded = quote(quote(iri, safe=""), safe="")
        url = f"{self._base_url}/ontologies/{ontology}/terms/{encoded}/hierarchicalAncestors"
        data = self._get_json(
            url,
            {"size": 200},
            description=f"OLS ancestors id={obo_id} ontology={ontology}",
        )
        terms = data.get("_embedded", {}).get("terms", [])
        return [self._to_term(term) for term in terms if term.get("obo_id")]

    @staticmethod
    def _to_term(doc: dict[str, Any]) -> OlsTerm:
        return OlsTerm(
            obo_id=doc.get("obo_id", ""),
            label=doc.get("label", ""),
            iri=doc.get("iri", ""),
            ontology_name=doc.get("ontology_name", ""),
        )
