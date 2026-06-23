# PARCE Architecture

> Status: design baseline for the `restructure-context-metadata` line of work.
> This document is the source of truth for *why* the code is shaped the way it
> is. Update it (with rationale) whenever a design decision changes.

## 1. Goal

Produce a single, ontology-grounded **knowledge graph** of public omics
experiments spanning **multiple modalities**, suitable as training data for a
downstream multi-omics autoregressive model. For each study the KG records:

- **Biological context** (study-level): assay/technology, tissue, disease,
  organism — the *design* variables.
- **Sample-level covariates**: condition, perturbation, timepoint, subject, and
  a URI to the raw data for that sample.

The downstream model treats samples within a study as a **context-conditioned
set** (not a sequence), and links studies across modalities through **shared
context**. Two consequences shape this repo:

- **Context must be design, not data-inferred outcome.** Cell type, cluster
  labels, etc. are excluded — they are downstream of the raw signal and would
  leak the learning target.
- **Cross-study/cross-modality linking flows through shared ontology nodes.** A
  bulk RNA-seq study and a single-cell study that both touch `MONDO:0005061`
  become connected in the graph. This is the data-layer realization of the
  model's "shared context space."

## 2. The modality / structure gradient

We deliberately ingest sources spanning a gradient of metadata structure, so the
extraction logic has a real but tractable job and the "one KG, many sources"
claim is proven early.

| Tier | Source | Modality | Metadata | LLM in path? |
|------|--------|----------|----------|--------------|
| Anchor | **CELLxGENE Census** | scRNA-seq | structured, ontology-grounded | No (deterministic) |
| Extraction start | **GEO** (NCBI) | bulk RNA-seq (+ ATAC/ChIP) | semi-structured free text (`characteristics_ch1`) | Yes (extraction agent) |
| Cross-modality | **PRIDE / ProteomeXchange** | proteomics (intensities) | free-text + partial SDRF | Yes (extraction agent) |

GEO is the first extraction target because (a) its metadata is the canonical
messy case, and (b) it overlaps biologically with CELLxGENE, so cross-source KG
edges appear with only two sources connected. PRIDE then proves modality
generality. (ENCODE is a clean structured alternative if a deterministic second
modality is wanted before proteomics.)

## 3. Layered design

```
                 ┌─────────────────────────────────────────────┐
   per source →  │  SourceAdapter:  discover(query) -> [ref]    │
                 │                  fetch(ref)      -> RawRecord │
                 └───────────────────────┬─────────────────────┘
                                         │ RawRecord (source-shaped)
                 ┌───────────────────────▼─────────────────────┐
   per source →  │  Normalizer:  RawRecord -> canonical nodes   │
                 │   • structured source -> deterministic map   │
                 │   • unstructured      -> Azure extraction    │
                 │                          agent (response_     │
                 │                          format = schema)    │
                 └───────────────────────┬─────────────────────┘
                                         │ canonical nodes w/ free-text terms
                 ┌───────────────────────▼─────────────────────┐
   shared     →  │  OntologyResolver: text -> UBERON/MONDO/...  │
                 │   deterministic (OLS/text2term) + cache,     │
                 │   LLM only as fallback for hard cases        │
                 └───────────────────────┬─────────────────────┘
                                         │ ontology-grounded nodes
                 ┌───────────────────────▼─────────────────────┐
   shared     →  │  GraphBuilder/Merger: assemble + merge into  │
                 │  one KG; entities deduped by ontology ID     │
                 └─────────────────────────────────────────────┘
```

### Why this shape

- **The canonical schema is the contract.** The deterministic path and the
  agent path emit the *same* Pydantic models. Per-source variation collapses to
  "which adapter + is the normalizer deterministic or agent-backed". Everything
  downstream is identical and source-agnostic.
- **The LLM is boxed in.** It lives only inside unstructured normalizers and is
  constrained by `response_format` to fill canonical fields — it cannot emit
  prose. This keeps the system testable and reproducible, and makes the agent's
  output directly comparable to the deterministic path.
- **Ontology resolution is a shared stage, not per-adapter.** All sources must
  land on the same IDs or the graph won't link. Deterministic resolvers are
  tried first (OLS, text2term); the LLM is a fallback for ambiguous strings.

## 4. Canonical KG schema

Source-agnostic nodes (Pydantic v2, `extra="forbid"`). Implemented in PR 2 in
`models/graph_schema.py`:

- `StudyNode` — `study_id` (DOI/accession), `title`, `source` (provenance),
  `modality`. *(No `experimental_narrative`; that field is removed.)* Raw free
  text (abstracts, full descriptions) is **not** stored on the node — it belongs
  to the per-source `RawRecord`; the canonical node holds only normalized,
  design-describing fields.
- `DatasetNode` — `dataset_id`, `data_uri`, `assay`, `cell_count`/size. Its
  parent study is a typed `EXTRACTED_FROM` **edge**, not a stored foreign-key
  field. *(Decision, PR 2: containment/relationships live on edges only;
  duplicating them as node fields invites drift and gives two sources of truth.)*
- `SampleNode` — `sample_id`, `data_uri`, and **design covariates**: `condition`,
  `perturbation`, `timepoint`, `subject`, `organism`. (Reintroduced; the prior
  schema was dataset-level only.) All covariates are optional — different
  sources populate different subsets. Linked to its dataset/study via a typed
  edge (e.g. `HAS_SAMPLE`).
- `BiologicalEntityNode` — `entity_type` ∈ {Disease, Tissue, Species,
  Perturbation, Assay}, `ontology_id`, `name`. **CellType is intentionally
  absent.**
- `GraphEdge` — typed, directed: `EXTRACTED_FROM` (Dataset→Study), `HAS_SAMPLE`
  (Dataset→Sample), `HAS_TISSUE` / `HAS_CONDITION` (Dataset→BiologicalEntity),
  `MEASURED_WITH` (Dataset→Assay), `STUDIES` (Study→Species), etc. `relation_type`
  is a free `str` for now (the vocabulary still grows as GEO/PRIDE land); it may
  become a `StrEnum` once the set stabilizes.

Cross-source links are *emergent*: two studies share an edge target
(`ontology_id`) rather than any source-specific key.

## 5. Coding style & architecture choices

- **Language/runtime:** Python ≥ 3.11, `src`-layout, `from __future__ import
  annotations` everywhere, full type hints on public APIs.
- **Data modeling:** Pydantic v2 at every boundary; KG models forbid extra
  fields. Schemas double as agent `response_format` and downstream validation.
- **Determinism boundary:** library code is pure/deterministic except inside
  `normalize` (for unstructured sources) and `agent`. Network IO is isolated in
  `sources`/`agent`/`ontology` so the core is unit-testable offline.
- **Interfaces over inheritance:** `SourceAdapter` and `Normalizer` are small
  `Protocol`/ABC contracts. Adding a source = new adapter + normalizer, no edits
  to orchestration or graph code.
- **Errors & resilience:** external calls use bounded retries with jittered
  exponential backoff; transient vs. terminal errors are distinguished.
- **Config:** `pydantic-settings` + `.env`; never hardcode endpoints/secrets.
- **Logging:** stdlib `logging` in libraries; `print` only for CLI summaries.
- **Quality gates (CI-enforced):** `ruff check`, `ruff format --check`,
  `mypy src/parce`, `pytest -m "not integration"`. See `pyproject.toml`.
- **Tests:** offline unit tests by default; live/credentialed tests carry the
  `integration` marker and are excluded from CI.

## 6. Open questions (track, don't silently decide)

- **Sample granularity for CELLxGENE.** Census is per-cell/dataset, not
  per-sample in the GEO sense. Defer mapping cxg to `SampleNode` until needed;
  keep it dataset-level for now.
- **Ontology resolver dependency.** text2term vs. a thin OLS REST client —
  decide when implementing `ontology/` (PR4); prefer the lighter dependency.
- **Graph persistence/export format** for the modeling step (per-study context +
  sample manifest + URIs). Specified in a later PR.
- **Multi-omics is core, not optional.** CELLxGENE alone cannot carry the
  vision; PRIDE (and beyond) is required, not a nice-to-have.
