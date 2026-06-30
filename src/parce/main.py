"""PARCE entry point — multi-source omics ingestion.

Drives a source through its adapter → normalizer pipeline and writes the canonical
knowledge graph to disk. Two source paths exist:

* ``cellxgene`` (default) — fully **deterministic**: CELLxGENE Census already ships
  ontology-grounded metadata, so there is no LLM here.
* ``geo`` — the first **agent-backed** path: GEO's free-text sample metadata is
  extracted into the canonical schema by the Azure extraction agent, then grounded
  through the shared ontology resolver (docs/ARCHITECTURE.md §2-3). This path needs
  Azure credentials (an ``az login`` session) at runtime.

Run with::

    parce                       # CELLxGENE, default DOI
    parce cellxgene <DOI>
    parce geo GSE10072          # GEO series (requires Azure creds)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from parce.graph import merge_subgraphs
from parce.models.graph_schema import KnowledgeGraphOutput
from parce.normalize.cellxgene import CellxgeneNormalizer
from parce.sources.cellxgene import CellxgeneAdapter

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "graphs"
_DEFAULT_DOI = "10.1038/s41586-023-05869-0"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _persist(kg: KnowledgeGraphOutput, *, filename: str = "output.json") -> None:
    """Print a summary of ``kg`` and write it to the output directory."""
    print("Knowledge graph constructed successfully:")
    print(f"  Studies:             {len(kg.studies)}")
    print(f"  Datasets:            {len(kg.datasets)}")
    print(f"  Samples:             {len(kg.samples)}")
    print(f"  Biological entities: {len(kg.biological_entities)}")
    print(f"  Edges:               {len(kg.edges)}")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUTPUT_DIR / filename
    out_path.write_text(json.dumps(kg.model_dump(mode="json"), indent=2))
    print(f"\nSaved to {out_path}")


def run(doi: str = _DEFAULT_DOI) -> None:
    """Fetch, normalize and persist the KG for a CELLxGENE collection DOI."""
    _configure_logging()

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
    # Step 3: Merge subgraphs (deduped by ontology ID) and persist.
    # ------------------------------------------------------------------
    logger.info("Step 3/3: Merging %d subgraph(s) and writing knowledge graph", len(subgraphs))
    _persist(merge_subgraphs(subgraphs))


def run_geo(accession: str) -> None:
    """Fetch, extract, ground and persist the KG for a GEO series accession.

    This is the agent-backed path: it builds the Azure extraction agent (needs an
    ``az login`` session + the Azure settings) and wires it both as the GEO
    normalizer's extractor *and* as the ontology resolver's LLM fallback for hard
    free-text terms. Imports of the Azure glue are deferred to here so the default
    CELLxGENE path and ``import parce.main`` need no Azure session.
    """
    _configure_logging()

    # Deferred imports: keep the Azure dependency off the default path / module import.
    from parce.agent.extraction import AzureExtractionAgent, make_ontology_fallback
    from parce.config.settings import Settings
    from parce.normalize.geo import GeoNormalizer
    from parce.ontology import OntologyResolver
    from parce.sources.geo import GeoAdapter

    settings = Settings()
    adapter = GeoAdapter(email=settings.ncbi_email, api_key=settings.ncbi_api_key)
    extractor = AzureExtractionAgent(settings)
    resolver = OntologyResolver(llm_fallback=make_ontology_fallback(extractor))
    normalizer = GeoNormalizer(extractor, resolver=resolver)

    refs = adapter.discover(accession)
    logger.info("Step 1/3: Discovered %d GEO reference(s) for query=%s", len(refs), accession)
    if not refs:
        logger.error("No GEO series found for query=%s", accession)
        return

    logger.info("Step 2/3: Fetching, extracting and normalizing %d reference(s)", len(refs))
    subgraphs: list[KnowledgeGraphOutput] = []
    for ref in refs:
        record = adapter.fetch(ref)
        if not record.payload.get("samples"):
            logger.warning("No samples for GEO ref=%s; skipping", ref)
            continue
        subgraphs.append(normalizer.normalize(record))

    if not subgraphs:
        logger.error("No samples fetched for query=%s", accession)
        return

    logger.info("Step 3/3: Merging %d subgraph(s) and writing knowledge graph", len(subgraphs))
    _persist(merge_subgraphs(subgraphs), filename=f"{accession.upper()}.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="parce", description="Harvest omics experiments into a KG."
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="cellxgene",
        choices=["cellxgene", "geo"],
        help="Which source to ingest (default: cellxgene).",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="CELLxGENE collection DOI or GEO series accession (GSEnnnnn).",
    )
    args = parser.parse_args()

    if args.source == "geo":
        if not args.query:
            parser.error(
                "the 'geo' source requires a GEO series accession, e.g. parce geo GSE10072"
            )
        run_geo(args.query)
    else:
        run(args.query or _DEFAULT_DOI)


if __name__ == "__main__":
    main()
