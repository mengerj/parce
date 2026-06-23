# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository. Read this
first, then [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and
[docs/ROADMAP.md](docs/ROADMAP.md) for what to do next.

## What PARCE is

PARCE harvests **public omics experiments** from heterogeneous repositories and
normalizes them into a single, ontology-grounded **knowledge graph (KG)**. The
KG is the training substrate for a downstream multi-omics autoregressive model:
each study contributes biological *context* (assay, tissue, disease, organism)
and sample-level *covariates* (condition, perturbation, timepoint, subject),
plus URIs to the raw data that an OQAE later tokenizes.

Two non-negotiable principles drive the design:

1. **Context is design, not outcome.** Only store metadata that describes how an
   experiment was *designed* — assay, tissue, disease, organism, perturbation.
   Never store data-*inferred* annotations (e.g. cell type called from
   expression). They leak the very signal the downstream model must learn.
2. **One canonical schema, many sources.** Every repository — structured or not —
   is mapped into the same Pydantic KG schema and the same ontology IDs. Sources
   link to each other *only* through shared ontology entity nodes.

## Where intelligence lives

The pipeline is **deterministic by default**. An LLM (Azure AI Foundry agent) is
used for exactly one job: **structured extraction and normalization of
free-text metadata** from unstructured sources (e.g. GEO, PRIDE). It is *never*
used to write prose/narrative, and it is constrained to emit the canonical
Pydantic schema via `response_format`. If a source already provides structured,
ontology-grounded metadata (e.g. CELLxGENE), there is **no LLM in its path**.

When you reach for the LLM, ask: "could a deterministic API call or an ontology
lookup do this?" If yes, do that instead.

## Project layout (target)

```
src/parce/
  models/      # Canonical Pydantic KG schema (nodes, edges, sample covariates)
  sources/     # One adapter per repository: discover() + fetch() -> RawRecord
  normalize/   # RawRecord -> canonical nodes (deterministic OR agent-backed)
  ontology/    # Shared free-text -> ontology-ID resolver (+ cache)
  agent/       # Azure extraction agent (structured output only)
  graph/       # Assemble + merge canonical nodes into one KG
  config/      # pydantic-settings configuration
  main.py      # CLI entry point / orchestrator
tests/         # Unit tests (offline) + integration tests (marked)
docs/          # ARCHITECTURE.md, ROADMAP.md, AGENT_SESSION_PROMPT.md
data_pipelines/  # Future: Spark/ADLS batch jobs
```

Dependency direction is one-way: `sources`, `normalize`, `agent`, `graph` all
depend on `models`; `models` depends on nothing. No import cycles.

## Coding conventions

- **Python ≥ 3.11**, `src`-layout, `from __future__ import annotations` in every
  module. Full type hints on public functions.
- **Pydantic v2** for all data at boundaries; KG models set
  `model_config = ConfigDict(extra="forbid")`.
- **Tooling (all enforced in CI):**
  - `ruff check .` — lint (rules: E, F, I, UP, B, SIM, C4, RUF).
  - `ruff format .` — formatting (line length 100). Never hand-format.
  - `mypy src/parce` — types. The stable core is checked; IO modules under
    `parce.tools.*` / `parce.agent.*` are temporarily exempt via
    `pyproject.toml` overrides. **Remove a module's exemption when you migrate
    it to the adapter interface** — do not add new exemptions.
  - `pytest -m "not integration"` — unit tests, must stay offline.
- **Tests:** unit tests must not touch the network, Azure, or Census — mock
  them. Anything that needs live credentials or downloads is marked
  `@pytest.mark.integration` and excluded from CI. **Unit tests must not depend
  on a local `.env`** — no unit test may construct `Settings()` unmocked.
  Verify hermeticity before reporting green: run the unit suite with `.env`
  moved aside (`mv .env .env.bak && uv run pytest -m "not integration"; mv
  .env.bak .env`), which reproduces the CI runner exactly.
- **Config & secrets:** all config via `pydantic-settings` (`config/settings.py`)
  and `.env`. Never hardcode endpoints or commit secrets; update `.env.example`
  when you add a setting. `data/` is gitignored.
- **Logging, not printing,** inside library code (stdlib `logging`). `print` is
  for CLI user-facing summaries only.
- **Resilience:** network calls to external repos/LLMs use bounded retries with
  jittered backoff (see the existing helpers in `main.py`).

## Environment & commands

uv-managed. Common commands:

```bash
uv sync --extra dev                 # install (incl. dev tools)
uv run parce                        # run the CLI
uv run ruff check . && uv run ruff format --check .
uv run mypy src/parce
uv run pytest -m "not integration"  # unit tests (CI gate)
uv run pytest -m integration        # live tests (needs Azure/Census)
uv lock                             # refresh lockfile after changing deps
```

Before opening a PR, all four gates (ruff check, ruff format --check, mypy,
pytest unit) must pass locally — they are exactly what CI runs.

## Working agreement (every session)

This repo is built across many short, fresh Claude Code sessions. To stay
coherent:

1. **Start** by reading `CLAUDE.md`, `docs/ARCHITECTURE.md`, and
   `docs/ROADMAP.md`. The roadmap's **"Next up"** marker is your task.
2. **Scope** one roadmap item per session/PR. Work on a feature branch, never
   commit directly to `main`.
3. **Finish** by updating `docs/ROADMAP.md`: tick the completed checklist items,
   append a dated entry to the **Session Log**, and move the **"Next up"**
   marker. The next session relies entirely on this — leave it accurate.
4. Keep `ARCHITECTURE.md` in sync if you change a design decision; record *why*.

Full session protocol: [docs/AGENT_SESSION_PROMPT.md](docs/AGENT_SESSION_PROMPT.md).
