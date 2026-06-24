"""PARCE entry point — deterministic CELLxGENE ingestion.

Drives one source through the adapter → normalizer pipeline and writes the
canonical knowledge graph to disk. CELLxGENE Census already ships
ontology-grounded metadata, so this path is fully deterministic — there is no
LLM here (the extraction agent enters with GEO in PR 5).

Run with::

    python -m parce.main

or, after ``pip install -e .``::

    parce
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from parce.models.graph_schema import KnowledgeGraphOutput
from parce.normalize.cellxgene import CellxgeneNormalizer
from parce.sources.cellxgene import CellxgeneAdapter

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "graphs"
_DEFAULT_DOI = "10.1038/s41586-023-05869-0"


def run(doi: str = _DEFAULT_DOI) -> None:
    """Fetch, normalize and persist the KG for a CELLxGENE collection DOI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    adapter = CellxgeneAdapter()
    normalizer = CellxgeneNormalizer()

    # ------------------------------------------------------------------
    # Step 1: Discover study references for the query.
    # ------------------------------------------------------------------
    refs = adapter.discover(doi)
    logger.info("Step 1/3: Discovered %d reference(s) for query=%s", len(refs), doi)
    if not refs:
        logger.error("No study references found for query=%s", doi)
        return

    # ------------------------------------------------------------------
    # Step 2: Fetch + normalize each reference into a canonical subgraph.
    # ------------------------------------------------------------------
    logger.info("Step 2/3: Fetching and normalizing %d reference(s)", len(refs))
    subgraphs: list[KnowledgeGraphOutput] = []
    for ref in refs:
        record = adapter.fetch(ref)
        if not record.payload.get("datasets"):
            logger.warning(
                "No datasets for ref=%s (%s); skipping",
                ref,
                record.payload.get("error", "empty"),
            )
            continue
        subgraphs.append(normalizer.normalize(record))

    if not subgraphs:
        logger.error("No datasets fetched for query=%s", doi)
        return

    # ------------------------------------------------------------------
    # Step 3: Persist the canonical KG.
    # ------------------------------------------------------------------
    # PR 3 is single-source/single-study, so there is exactly one subgraph here.
    # Merging multiple subgraphs into one graph (deduped by ontology ID) is PR 6.
    logger.info("Step 3/3: Writing knowledge graph")
    kg = subgraphs[0]

    print("Knowledge graph constructed successfully:")
    print(f"  Studies:             {len(kg.studies)}")
    print(f"  Datasets:            {len(kg.datasets)}")
    print(f"  Samples:             {len(kg.samples)}")
    print(f"  Biological entities: {len(kg.biological_entities)}")
    print(f"  Edges:               {len(kg.edges)}")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUTPUT_DIR / "output.json"
    out_path.write_text(json.dumps(kg.model_dump(mode="json"), indent=2))
    print(f"\nSaved to {out_path}")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
