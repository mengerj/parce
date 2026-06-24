# PARCE

**Programmable Agent for Retrieving Contextualized Experiments**

PARCE harvests **public omics experiments** from heterogeneous repositories and
normalizes them into a single, ontology-grounded **knowledge graph (KG)**. The KG
is the training substrate for a downstream multi-omics autoregressive model: each
study contributes biological *context* (assay, tissue, disease, organism) and
sample-level *covariates* (condition, perturbation, timepoint, subject), plus URIs
to the raw data.

Two principles drive the design:

1. **Context is design, not outcome.** Only metadata that describes how an
   experiment was *designed* is stored. Data-inferred annotations (e.g. cell type
   called from expression) are excluded — they would leak the signal the
   downstream model must learn.
2. **One canonical schema, many sources.** Every repository is mapped into the
   same Pydantic KG schema and the same ontology IDs. Sources link to each other
   *only* through shared ontology entity nodes.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and
[docs/ROADMAP.md](docs/ROADMAP.md) for the plan and current status.

## Architecture

The pipeline is **deterministic by default**. Each repository has a `SourceAdapter`
(all network IO) that emits source-shaped `RawRecord`s, and a `Normalizer` that
maps a `RawRecord` into canonical KG nodes. An LLM is used for exactly one job —
structured extraction from *unstructured* free-text metadata (e.g. GEO, PRIDE),
constrained to the canonical schema via `response_format`. Structured,
ontology-grounded sources (e.g. CELLxGENE) have **no LLM in their path**.

```
 per source →  SourceAdapter:  discover(query) -> [ref]
                               fetch(ref)      -> RawRecord
                                     │ (source-shaped)
 per source →  Normalizer:     RawRecord -> canonical KG nodes
                 • structured source -> deterministic map
                 • unstructured      -> Azure extraction agent (PR 5+)
                                     │ (canonical nodes w/ free-text terms)
 shared     →  OntologyResolver: text -> UBERON/MONDO/EFO/... (PR 4)
                                     │ (ontology-grounded nodes)
 shared     →  GraphBuilder/Merger: assemble + merge into one KG (PR 6)
```

The canonical schema (`models/graph_schema.py`) is the contract: the deterministic
path and the future agent path emit the *same* Pydantic models, so everything
downstream is source-agnostic.

### Directory structure

```
src/parce/
  models/      # Canonical Pydantic KG schema + RawRecord (boundary model)
  sources/     # One adapter per repository: discover() + fetch() -> RawRecord
  normalize/   # RawRecord -> canonical nodes (deterministic OR agent-backed)
  agent/       # Azure extraction agent (structured output only; PR 5+)
  graph/       # Cross-source KG assembly + merge (PR 6)
  config/      # pydantic-settings configuration
  main.py      # CLI entry point / orchestrator
tests/         # Unit tests (offline) + integration tests (marked)
docs/          # ARCHITECTURE.md, ROADMAP.md, AGENT_SESSION_PROMPT.md
```

Implemented so far: the canonical schema, the `SourceAdapter`/`Normalizer`
protocols, and the deterministic **CELLxGENE** adapter + normalizer.

## Setup

PARCE is [uv](https://docs.astral.sh/uv/)-managed.

```bash
uv sync --extra dev      # install (incl. dev tools)
uv run parce             # run the CLI (CELLxGENE path; deterministic)
```

`parce` fetches the datasets for the default collection DOI from CELLxGENE Census,
normalizes them into the canonical KG, and writes `data/graphs/output.json`. This
path needs only network access — **no Azure credentials**.

Azure AI Foundry credentials are required only for the extraction agent (GEO/PRIDE,
PR 5+) and for the integration test suite. Copy `.env.example` to `.env` and fill
in your Foundry endpoint and deployment name, then `az login`.

## Tests & quality gates

CI runs four gates; all four must pass locally before opening a PR:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/parce
uv run pytest -m "not integration"   # unit tests (offline, hermetic)
```

Live/credentialed tests carry the `integration` marker and are excluded from CI:

```bash
uv run pytest -m integration         # needs Azure / Census / network
```
