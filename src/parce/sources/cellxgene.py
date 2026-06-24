"""CELLxGENE Census source adapter — deterministic, no LLM in the path.

Queries the Census datasets table by collection DOI, resolves each dataset's
H5AD URI, and summarises the *design-context* ontology terms (tissue, disease,
assay, organism) found in the cell metadata. CELLxGENE already ships these terms
ontology-grounded, so no extraction agent is needed.

Cell type is intentionally **not** read: it is a data-inferred annotation (called
from expression), not an experiment-design variable, and carrying it would leak
the very signal the downstream model must learn. See docs/ARCHITECTURE.md §1.

The Census/EuropePMC calls are the only network IO here; the matching mapper is
:class:`parce.normalize.cellxgene.CellxgeneNormalizer`.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import cellxgene_census

from parce.models.raw_record import RawRecord
from parce.sources._retry import with_retries
from parce.sources.publication import fetch_paper_metadata

logger = logging.getLogger(__name__)

SOURCE_NAME = "CELLxGENE"

_MAX_TERMS_PER_CATEGORY = 50

# Cell-type columns are deliberately omitted (data-inferred → leakage).
_ONTOLOGY_COLUMNS = [
    "tissue",
    "tissue_ontology_term_id",
    "disease",
    "disease_ontology_term_id",
    "assay",
    "assay_ontology_term_id",
]

# Census splits cell metadata per organism; we try each until one yields rows.
_ORGANISM_CANDIDATES = [
    "Homo sapiens",
    "Mus musculus",
    "homo_sapiens",
    "mus_musculus",
]


def _extract_term_pairs(obs: Any, name_col: str, id_col: str) -> list[dict[str, str]]:
    """Deduplicate and return structured ontology term pairs, capped."""
    unique = obs[[name_col, id_col]].drop_duplicates()
    terms = sorted(
        [{"name": row[name_col], "ontology_id": row[id_col]} for _, row in unique.iterrows()],
        key=lambda t: t["name"],
    )
    return terms[:_MAX_TERMS_PER_CATEGORY]


def _summarise_ontology_terms(census: Any, dataset_id: str) -> dict[str, Any]:
    """Return structured design-context ontology data for a single dataset."""
    last_error: str | None = None
    for organism in _ORGANISM_CANDIDATES:
        try:
            t0 = time.perf_counter()
            obs = with_retries(
                cellxgene_census.get_obs,
                census,
                organism,
                column_names=_ONTOLOGY_COLUMNS,
                value_filter=f"dataset_id == '{dataset_id}'",
                description=f"Census get_obs dataset_id={dataset_id} organism={organism}",
            )
            elapsed = time.perf_counter() - t0
            logger.info(
                "Census obs loaded dataset_id=%s organism=%s rows=%d (%.2fs)",
                dataset_id,
                organism,
                len(obs),
                elapsed,
            )
            if obs.empty:
                continue

            assay_counts = obs["assay"].value_counts(dropna=True)
            modality = assay_counts.index[0] if not assay_counts.empty else "unknown"

            return {
                "organism": organism,
                "modality": modality,
                "tissues": _extract_term_pairs(obs, "tissue", "tissue_ontology_term_id"),
                "diseases": _extract_term_pairs(obs, "disease", "disease_ontology_term_id"),
                "assays": _extract_term_pairs(obs, "assay", "assay_ontology_term_id"),
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.info(
                "Failed get_obs for dataset_id=%s organism=%s (%s)",
                dataset_id,
                organism,
                last_error,
            )
            continue

    empty: dict[str, Any] = {
        "organism": "unknown",
        "modality": "unknown",
        "tissues": [],
        "diseases": [],
        "assays": [],
    }
    if last_error is not None:
        empty["error"] = last_error
    return empty


def _process_single_dataset(census: Any, row: Any) -> dict[str, Any]:
    """Resolve URI and ontology terms for one dataset row (thread-safe)."""
    dataset_id = row["dataset_id"]

    try:
        t_uri = time.perf_counter()
        uri_info = with_retries(
            cellxgene_census.get_source_h5ad_uri,
            dataset_id,
            description=f"Census get_source_h5ad_uri dataset_id={dataset_id}",
        )
        h5ad_uri = uri_info["uri"]
        logger.info(
            "Resolved H5AD URI dataset_id=%s (%.2fs)",
            dataset_id,
            time.perf_counter() - t_uri,
        )
    except Exception:
        h5ad_uri = f"s3://cellxgene-data-public/cell-census/h5ads/{dataset_id}.h5ad"

    ontology_summary = _summarise_ontology_terms(census, dataset_id)

    return {
        "dataset_id": dataset_id,
        "dataset_title": row["dataset_title"],
        "h5ad_uri": h5ad_uri,
        "modality": ontology_summary.get("modality", "unknown"),
        "cell_count": int(row["dataset_total_cell_count"]),
        "ontology_summary": ontology_summary,
    }


def fetch_cellxgene_datasets(doi: str, *, max_workers: int = 4) -> dict[str, Any]:
    """Fetch CELLxGENE dataset metadata for a collection DOI as a plain dict.

    Returns ``{"doi": doi, "datasets": [...]}`` where each dataset carries its
    H5AD URI, cell count and a structured ontology summary (tissues, diseases,
    assays — each a list of ``{"name", "ontology_id"}`` — plus organism). When no
    dataset matches the DOI, ``datasets`` is empty and an ``error`` key is added.
    Per-dataset URI resolution and ontology queries run in parallel threads.
    """
    t_all = time.perf_counter()
    logger.info("Opening CELLxGENE Census")
    census = with_retries(cellxgene_census.open_soma, description="Census open_soma")
    try:
        t0 = time.perf_counter()
        datasets_df = with_retries(
            lambda: census["census_info"]["datasets"].read().concat().to_pandas(),
            description="Census datasets table read",
        )
        logger.info(
            "Loaded Census datasets table rows=%d (%.2fs)",
            len(datasets_df),
            time.perf_counter() - t0,
        )
        matched = datasets_df[datasets_df["collection_doi"] == doi]

        if matched.empty:
            logger.info("No datasets matched DOI=%s", doi)
            return {"doi": doi, "datasets": [], "error": f"No datasets found for DOI {doi}"}

        total = len(matched)
        logger.info(
            "Matched DOI=%s datasets=%d, processing with %d workers", doi, total, max_workers
        )

        rows = [row for _, row in matched.iterrows()]

        results: list[dict[str, Any]]
        if total == 1:
            results = [_process_single_dataset(census, rows[0])]
        else:
            results = [{} for _ in range(total)]
            with ThreadPoolExecutor(max_workers=min(max_workers, total)) as pool:
                future_to_idx = {
                    pool.submit(_process_single_dataset, census, row): i
                    for i, row in enumerate(rows)
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    results[idx] = future.result()
                    logger.info("Completed dataset %d/%d", idx + 1, total)

        logger.info(
            "CELLxGENE fetch complete DOI=%s datasets=%d total_time=%.2fs",
            doi,
            len(results),
            time.perf_counter() - t_all,
        )
        return {"doi": doi, "datasets": results}
    finally:
        logger.info("Closing CELLxGENE Census")
        census.close()


class CellxgeneAdapter:
    """:class:`~parce.sources.base.SourceAdapter` for CELLxGENE Census.

    Deterministic: CELLxGENE already emits ontology-grounded terms, so there is
    no LLM anywhere in this source's path.
    """

    source_name = SOURCE_NAME

    def discover(self, query: str) -> list[str]:
        """Resolve ``query`` (a collection DOI) to study references.

        For CELLxGENE a study is a Census collection identified by its DOI, so the
        DOI *is* the reference and ``discover`` is the identity on it. Keyword
        collection search is future work (see docs/ROADMAP.md backlog).
        """
        return [query]

    def fetch(self, ref: str, *, max_workers: int = 4) -> RawRecord:
        """Fetch one collection DOI into a source-shaped ``RawRecord``.

        Gathers the publication title (EuropePMC) and the per-dataset Census
        metadata. The payload carries ``datasets`` (possibly empty) and, when the
        DOI matched nothing, an ``error`` string for the caller to act on.
        """
        paper = fetch_paper_metadata(ref)
        cellxgene = fetch_cellxgene_datasets(ref, max_workers=max_workers)

        payload: dict[str, Any] = {"datasets": cellxgene.get("datasets", [])}
        if "error" in cellxgene:
            payload["error"] = cellxgene["error"]

        return RawRecord(
            source=self.source_name,
            study_id=ref,
            title=paper.get("title", ""),
            payload=payload,
        )
