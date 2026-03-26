"""PARCE entry point -- hybrid orchestrator.

Calls data tools directly from Python, sends a compact context to the LLM
for narrative generation, then assembles the Knowledge Graph programmatically.

Run with:
    python -m parce.main
or, after ``pip install -e .``:
    parce
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path

from parce.agent.curator import create_narrative_agent
from parce.config.settings import Settings
from parce.graph.builder import build_knowledge_graph
from parce.models.graph_schema import NarrativeOutput
from parce.tools.cellxgene_fetcher import fetch_cellxgene_datasets
from parce.tools.ncbi_fetcher import fetch_paper_metadata

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "graphs"
_DEFAULT_DOI = "10.1038/s41586-023-05869-0"

# Resilience constants
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0

# Transient HTTP status codes and exception types that warrant a retry
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_TRANSIENT_EXCEPTIONS = (TimeoutError, ConnectionError, OSError)


def _is_transient(exc: BaseException) -> bool:
    """Return True if the exception looks transient and worth retrying."""
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    from azure.core.exceptions import HttpResponseError
    if isinstance(exc, HttpResponseError) and exc.status_code in _TRANSIENT_STATUS_CODES:
        return True
    return False


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter."""
    delay = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
    return random.uniform(0, delay)


def _build_narrative_prompt(paper_data: dict, cellxgene_data: dict) -> str:
    """Build a compact text prompt from tool outputs for the narrative agent."""
    lines = [f"## Publication\nTitle: {paper_data.get('title', 'N/A')}"]

    abstract = paper_data.get("abstract", "")
    if abstract:
        lines.append(f"Abstract: {abstract}")

    datasets = cellxgene_data.get("datasets", [])
    if datasets:
        lines.append(f"\n## CELLxGENE Datasets ({len(datasets)} total)")
        for ds in datasets:
            ontology = ds.get("ontology_summary", {})
            parts = [f"- **{ds['dataset_id']}**: {ds.get('modality', '?')}, {ds['cell_count']:,} cells"]
            for category in ("cell_types", "tissues", "diseases", "assays"):
                terms = ontology.get(category, [])
                if terms:
                    names = [t["name"] for t in terms[:10]]
                    suffix = f" (+{len(terms) - 10} more)" if len(terms) > 10 else ""
                    parts.append(f"  {category}: {', '.join(names)}{suffix}")
            organism = ontology.get("organism", "unknown")
            parts.append(f"  organism: {organism}")
            lines.append("\n".join(parts))

    lines.append("\nWrite the experimental narrative now.")
    return "\n".join(lines)


async def run(doi: str = _DEFAULT_DOI) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    settings = Settings()

    # ------------------------------------------------------------------
    # Step 1: Fetch data directly from Python (no agent tool-calling)
    # ------------------------------------------------------------------
    logger.info("Step 1/3: Fetching data for DOI=%s", doi)

    t0 = time.perf_counter()
    paper_data = fetch_paper_metadata(doi)
    paper_elapsed = time.perf_counter() - t0
    logger.info(
        "Paper metadata fetched: title=%r chars=%d (%.2fs)",
        paper_data.get("title", "")[:60],
        len(json.dumps(paper_data, separators=(",", ":"))),
        paper_elapsed,
    )

    t0 = time.perf_counter()
    cellxgene_data = fetch_cellxgene_datasets(doi)
    cellxgene_elapsed = time.perf_counter() - t0
    n_datasets = len(cellxgene_data.get("datasets", []))
    logger.info(
        "CELLxGENE data fetched: datasets=%d chars=%d (%.2fs)",
        n_datasets,
        len(json.dumps(cellxgene_data, separators=(",", ":"))),
        cellxgene_elapsed,
    )

    if "error" in cellxgene_data and not cellxgene_data.get("datasets"):
        logger.error("No datasets found: %s", cellxgene_data["error"])
        return

    # ------------------------------------------------------------------
    # Step 2: Generate narrative via LLM (with resilience)
    # ------------------------------------------------------------------
    logger.info("Step 2/3: Generating experimental narrative via LLM")
    prompt = _build_narrative_prompt(paper_data, cellxgene_data)
    logger.info("Narrative prompt chars=%d", len(prompt))

    narrative: str | None = None
    async with create_narrative_agent(settings) as agent:
        for attempt in range(settings.max_retries):
            try:
                t0 = time.perf_counter()
                result = await agent.run(
                    prompt,
                    response_format=NarrativeOutput,
                    options={"temperature": 0},
                )
                llm_elapsed = time.perf_counter() - t0

                # Log token usage if available
                usage = getattr(result, "usage", None)
                if usage:
                    logger.info(
                        "LLM usage: prompt_tokens=%s completion_tokens=%s total_tokens=%s (%.2fs)",
                        getattr(usage, "prompt_tokens", "?"),
                        getattr(usage, "completion_tokens", "?"),
                        getattr(usage, "total_tokens", "?"),
                        llm_elapsed,
                    )
                else:
                    logger.info("LLM call completed (%.2fs)", llm_elapsed)

                if result.value:
                    narrative = result.value.experimental_narrative
                    logger.info("Narrative generated via response_format: %d chars", len(narrative))
                    break

                # Fallback: AzureAIAgentClient may not support response_format,
                # in which case result.text is the narrative as plain text.
                text = (result.text or "").strip()
                if not text:
                    raise ValueError("Agent returned empty response")

                # Try JSON parse first (model might have returned JSON anyway)
                try:
                    parsed = NarrativeOutput.model_validate_json(text)
                    narrative = parsed.experimental_narrative
                except Exception:
                    narrative = text
                logger.info("Narrative generated via text fallback: %d chars", len(narrative))
                break

            except Exception as exc:
                if _is_transient(exc) and attempt < settings.max_retries - 1:
                    delay = _backoff_delay(attempt)
                    logger.warning(
                        "Transient error on attempt %d/%d, retrying in %.1fs: %s",
                        attempt + 1, settings.max_retries, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("LLM narrative generation failed: %s", exc, exc_info=True)
                raise

    if narrative is None:
        logger.error("Failed to generate narrative after %d attempts", settings.max_retries)
        return

    # ------------------------------------------------------------------
    # Step 3: Build the Knowledge Graph programmatically
    # ------------------------------------------------------------------
    logger.info("Step 3/3: Assembling knowledge graph")
    kg = build_knowledge_graph(paper_data, cellxgene_data, narrative)

    print("Knowledge graph constructed successfully:")
    print(f"  Publications:        {len(kg.publications)}")
    print(f"  Datasets:            {len(kg.datasets)}")
    print(f"  Biological entities: {len(kg.biological_entities)}")
    print(f"  Edges:               {len(kg.edges)}")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUTPUT_DIR / "output.json"
    payload = kg.model_dump(mode="json")
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved to {out_path}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
