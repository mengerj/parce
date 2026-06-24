"""Tool for fetching dataset metadata and ontology terms from CELLxGENE Census.

Queries the Census datasets table by collection DOI, retrieves per-dataset
H5AD URIs, and summarises the unique ontology terms (cell types, tissues,
diseases, assays) found in the cell metadata.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated

import cellxgene_census
from agent_framework import tool
from pydantic import Field

from parce.sources._retry import with_retries

logger = logging.getLogger(__name__)

_MAX_TERMS_PER_CATEGORY = 50

_ONTOLOGY_COLUMNS = [
    "cell_type",
    "cell_type_ontology_term_id",
    "tissue",
    "tissue_ontology_term_id",
    "disease",
    "disease_ontology_term_id",
    "assay",
    "assay_ontology_term_id",
]

_ORGANISM_CANDIDATES = [
    "Homo sapiens",
    "Mus musculus",
    "homo_sapiens",
    "mus_musculus",
]

_ORGANISM_ONTOLOGY: dict[str, tuple[str, str]] = {
    "Homo sapiens": ("NCBITaxon:9606", "Homo sapiens"),
    "Mus musculus": ("NCBITaxon:10090", "Mus musculus"),
    "homo_sapiens": ("NCBITaxon:9606", "Homo sapiens"),
    "mus_musculus": ("NCBITaxon:10090", "Mus musculus"),
}


def _extract_term_pairs(obs, name_col: str, id_col: str) -> list[dict[str, str]]:
    """Deduplicate and return structured ontology term pairs, capped."""
    unique = obs[[name_col, id_col]].drop_duplicates()
    terms = sorted(
        [{"name": row[name_col], "ontology_id": row[id_col]} for _, row in unique.iterrows()],
        key=lambda t: t["name"],
    )
    return terms[:_MAX_TERMS_PER_CATEGORY]


def _summarise_ontology_terms(census, dataset_id: str) -> dict:
    """Return structured ontology term data for a single dataset."""
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
                "cell_types": _extract_term_pairs(obs, "cell_type", "cell_type_ontology_term_id"),
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

    empty: dict = {
        "organism": "unknown",
        "modality": "unknown",
        "cell_types": [],
        "tissues": [],
        "diseases": [],
        "assays": [],
    }
    if last_error is not None:
        empty["error"] = last_error
    return empty


def _process_single_dataset(census, row) -> dict:
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


def fetch_cellxgene_datasets(doi: str, *, max_workers: int = 4) -> dict:
    """Core function: fetch CELLxGENE data and return a Python dict.

    This is the programmatic entry point used by the orchestrator.
    Returns structured ontology terms as lists of ``{"name": ..., "ontology_id": ...}`` dicts.
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

        if total == 1:
            results = [_process_single_dataset(census, rows[0])]
        else:
            results = [None] * total
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


@tool
def fetch_cellxgene_data(
    doi: Annotated[str, Field(description="Collection DOI (e.g. '10.1038/s41586-023-05869-0')")],
) -> str:
    """Fetch dataset metadata and ontology summaries from CELLxGENE Census for a DOI.

    Returns a JSON string listing each dataset associated with the DOI,
    including the remote H5AD URI, cell count, and unique ontology terms
    (cell types, tissues, diseases, assays).
    """
    return json.dumps(fetch_cellxgene_datasets(doi), separators=(",", ":"))
