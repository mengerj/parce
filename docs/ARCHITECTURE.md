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
  design-describing fields. *(Target, §5: this free-text `modality` is refined
  into an EFO `assay` term plus a derived coarse `molecular_layer` enum — PR 4.)*
- `DatasetNode` — `dataset_id`, `data_uri`, `assay` (to be grounded to an EFO
  term ID, see §5), `cell_count`/size. Its parent study is a typed
  `EXTRACTED_FROM` **edge**, not a stored foreign-key field. *(Decision, PR 2:
  containment/relationships live on edges only; duplicating them as node fields
  invites drift and gives two sources of truth.)*
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

## 5. Ontology grounding

Every facet of an experiment is bound to **one designated ontology**, never a
free-text string. This is what makes context a real metric space — the
precondition for cross-source linking and for the downstream model's shared
context space.

### Facet → ontology registry

This registry is a constant in `parce/ontology/` and the single source of truth
for "which vocabulary annotates which field".

| Facet | Ontology | Notes |
|-------|----------|-------|
| Assay / platform | **EFO** | Cross-domain assay branch (scRNA-seq, ATAC-seq, MS proteomics, …). CELLxGENE already emits EFO assay IDs. |
| Assay (upper-level / fallback) | **OBI** | Where EFO lacks a term. |
| MS proteomics specifics | **PSI-MS CV** | Instruments / acquisition; matches SDRF-Proteomics. |
| Tissue / anatomy | **UBERON** | Sample source. |
| Disease / condition | **MONDO** | Unified; prefer over bare DOID. |
| Organism | **NCBITaxon** | Already in use. |
| Cell type | **CL** | Exists but **excluded as context** (data-inferred → leakage). |
| Chemical / drug perturbation | **ChEBI** | Compound treatments. |
| Genetic perturbation | gene ID (**Ensembl**/**HGNC**) + action vocab | No clean single ontology for knockout vs. knockdown; pair gene ID with a small controlled action term. |
| Data format | **EDAM** | FASTQ/BAM/mzML/H5AD as typed terms. |

### "Modality" is two controlled fields, not one string

Avoid a free-text `modality`. Instead store, per dataset/study:

1. **`assay`** — a precise **EFO term ID** (resolved once from free text, then
   stable). Fine-grained (every 10x chemistry is its own term).
2. **`molecular_layer`** — a coarse enum `{genome, epigenome, transcriptome,
   proteome, metabolome, …}` **derived deterministically by walking the EFO
   term's `is-a` ancestors** to a small set of anchor classes. The lineage does
   the classification; we never re-string it.

> **PR 4 — anchors & default.** `MolecularLayer` lives in `models/graph_schema.py`
> (canonical-vocabulary home); the derivation is `parce.ontology.layers.
> derive_molecular_layer`. The anchor set is keyed by EFO ancestor **label**, not
> term ID — honouring "pin ontologies/anchors, not IDs" (OLS returns canonical
> labels for every ancestor), and matched most-specific-first. The **no-anchor
> default is `MolecularLayer.UNKNOWN`**. The current anchor labels are
> *provisional* (an informed first cut not yet checked against live EFO); the
> marked `tests/test_ontology_integration.py` is the validation harness, and PR 4b
> (which adds the stored field) must tighten them. The derivation logic + default
> are decided; only the exact label strings remain to be confirmed.

The model sees a clean cross-modality categorical (`molecular_layer`) plus a
precise term (`assay`) — both controlled, no free text on either.

### Resolution (deterministic-first; see §3)

- **OLS4** (EBI Ontology Lookup Service) — one REST API to search free text →
  candidate terms and to validate an ID + fetch ancestors (used for the
  `molecular_layer` lineage walk).
- **text2term** / **Zooma** — batch free-text → term mapping (Zooma is well
  suited to messy GEO characteristics).
- **OxO** — cross-ontology ID mapping when sources disagree (e.g. DOID → MONDO).
- **LLM** — fallback only, for strings the deterministic resolvers can't
  confidently map.

> **PR 4 — what shipped, and why OLS4-only (for now).** The stage is implemented
> in `parce/ontology/` as `OntologyResolver` (cache → OLS4 exact-then-fuzzy →
> optional LLM fallback) over the registry above. **Only OLS4 is wired**;
> text2term/Zooma are deferred to PR 5, where GEO's messy `characteristics_ch1`
> strings actually need fuzzy batch mapping. CELLxGENE already ships ontology IDs
> for tissue/disease/assay, so the only free-text grounding needed today is the
> organism string → NCBITaxon. The **LLM fallback is a pluggable `Callable`
> (default `None`)**, not a hard dependency — this keeps `ontology` free of any
> `parce.agent`/Azure import (dependency direction holds); PR 5 supplies the
> extraction agent as the callback. Resolutions are memoised to an on-disk cache
> (negative results included) so runs are reproducible and don't re-query.

Template to follow rather than reinvent: **SDRF / MAGE-TAB** (and
**SDRF-Proteomics**) already specify per-sample, ontology-annotated experiment
description and *which ontology per column* — almost exactly the `SampleNode` +
this registry. Aligning to it also yields free structured terms from sources
that already ship SDRF.

> Specific EFO/MONDO/etc. IDs are **resolved/validated via OLS at runtime**, not
> hardcoded from memory. The registry pins *ontologies*, not term IDs.

## 6. Coding style & architecture choices

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

## 7. Open questions (track, don't silently decide)

- **Sample granularity for CELLxGENE.** Census is per-cell/dataset, not
  per-sample in the GEO sense. Defer mapping cxg to `SampleNode` until needed;
  keep it dataset-level for now.
- **`molecular_layer` anchor set.** *Partly resolved (PR 4):* the derivation
  mechanism and the no-anchor default (`UNKNOWN`) are pinned, and the anchors are
  keyed by EFO **label**. **Still open:** the exact label strings are provisional
  and unvalidated against live EFO — confirm via the marked integration test and
  tighten in PR 4b.
- **Ontology resolver dependency.** *Resolved (PR 4):* **OLS4 REST only** for
  now (it covers organism grounding + the lineage walk). text2term/Zooma are
  deferred to PR 5, where GEO's messy `characteristics_ch1` strings need fuzzy
  batch mapping — add the lightest option that covers them then.
- **Graph persistence/export format** for the modeling step (per-study context +
  sample manifest + URIs). Specified in a later PR.
- **Multi-omics is core, not optional.** CELLxGENE alone cannot carry the
  vision; PRIDE (and beyond) is required, not a nice-to-have.
