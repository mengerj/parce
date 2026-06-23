# PARCE Roadmap

Living plan. **Each session reads this to find its task and updates it before
finishing.** See [AGENT_SESSION_PROMPT.md](AGENT_SESSION_PROMPT.md) for the
protocol and [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

---

## ▶ Next up

**PR 2 — Canonical KG schema refactor.** Introduce the source-agnostic schema
(`StudyNode`, `DatasetNode`, `SampleNode`, `BiologicalEntityNode`, `GraphEdge`),
reintroduce sample-level covariates, and **remove the narrative field and the
CellType entity**. Migrate `graph/builder.py` and tests. No new source yet.

---

## PR sequence

Each PR is one branch, one focused scope, green CI, and a roadmap update.

- [x] **PR 1 — Foundations & tooling.** CLAUDE.md, docs (architecture, roadmap,
  session prompt), GitHub Actions CI (ruff, mypy, pytest), ruff rule set + mypy
  config in `pyproject.toml`, code formatted to baseline. No behavior change.
- [ ] **PR 2 — Canonical KG schema.** Source-agnostic nodes/edges; add
  `SampleNode` with design covariates; replace free-text `modality` with `assay`
  (EFO term ref) + a coarse `molecular_layer` enum; drop `experimental_narrative`
  and `CellType`. Migrate builder + tests. *(Next up. See ARCHITECTURE §4–5.)*
- [ ] **PR 3 — Source-adapter interface + cheap CELLxGENE adapter.** Define
  `SourceAdapter` / `Normalizer` protocols in `sources/` + `normalize/`. Refactor
  CELLxGENE into a deterministic adapter. **Remove the LLM/Azure narrative path
  entirely** (delete `agent/prompts.py` narrative role, `models/narrative.py`,
  the step-2 block in `main.py`). Drop cell-type extraction. Remove the
  `parce.tools.*` mypy exemption as those modules move under `sources/`.
- [ ] **PR 4 — Ontology resolver.** Shared `ontology/` stage (see ARCHITECTURE
  §5). Pin the **facet → ontology registry** as a constant (EFO, UBERON, MONDO,
  NCBITaxon, ChEBI, PSI-MS, EDAM). Implement free-text → term resolution
  (OLS4 REST + text2term/Zooma, on-disk cache; LLM fallback) and the
  **`molecular_layer` derivation** (walk EFO `is-a` ancestors to anchor classes).
  Decide the anchor set + the no-anchor default. Wire into normalizers. Resolve
  IDs at runtime via OLS — do not hardcode term IDs.
- [ ] **PR 5 — GEO extraction agent (vertical slice).** GEO adapter
  (E-utilities/GEOparse) + Azure extraction normalizer emitting the canonical
  schema via `response_format`; extract sample covariates from
  `characteristics_ch1`. Integration test (marked). This is the agent's real
  job; remove the `parce.agent.*` mypy exemption.
- [ ] **PR 6 — Cross-source KG merge.** Merge CELLxGENE + GEO into one graph
  linked through shared ontology entities; dedup; provenance on edges. Assert a
  cross-source edge exists in tests.
- [ ] **PR 7 — PRIDE proteomics adapter.** Second modality; prove the interface
  is modality-general. Adapter + extraction normalizer + integration test.
- [ ] **PR 8 — KG export for modeling.** Serialize per-study context + sample
  manifest + data URIs in the form the downstream OQAE/model consumes.

## Backlog / ideas

- ENCODE adapter (clean structured epigenomics) if a deterministic second
  modality is wanted.
- Imaging modality (IDR / Human Protein Atlas) — needs a different OQAE encoder.
- Graph database backend (Neo4j) vs. flat JSON export — revisit at PR 8.
- Discovery agent: given a research theme, propose seed DOIs/accessions across
  repositories.

---

## Session Log

Newest first. One entry per working session: what changed, decisions made, and
what the next session should know. Keep entries short and factual.

### 2026-06-23 — Ontology grounding (docs)
- Decision: every experiment facet binds to one designated ontology (EFO assay,
  UBERON tissue, MONDO disease, NCBITaxon organism, ChEBI/gene-ID perturbation,
  PSI-MS for MS proteomics, EDAM data format). Registry lives in `parce/ontology/`.
- Decision: **no free-text `modality`.** Store `assay` (EFO term ID) + a coarse
  `molecular_layer` enum derived by walking EFO `is-a` ancestors. Both controlled.
- Decision: resolve term IDs at runtime via OLS4 (+ text2term/Zooma, LLM
  fallback); never hardcode IDs. Follow SDRF/MAGE-TAB conventions for the record.
- Updated ARCHITECTURE §4–5 (new §5 Ontology grounding; later sections renumbered)
  and sharpened ROADMAP PR 2 (`assay`+`molecular_layer`) and PR 4 (registry +
  lineage derivation + anchor-set open question).
- No code change; the orchestration CI fix (`6eb2fc9`) and action bump (`9f8403c`)
  remain the latest functional state. **Next up unchanged: PR 2.**

### 2026-06-23 — PR 1: Foundations & tooling
- Branch `restructure-context-metadata` off `main` (post-cxg-merge).
- Decision: the LLM is repurposed from **narrative writing** to **structured
  extraction from unstructured metadata**; Azure is kept to serve that (and as a
  learning goal). Deterministic-by-default everywhere else.
- Decision: multi-modality is core. Source gradient chosen: CELLxGENE (anchor,
  no LLM) → GEO (first extraction target) → PRIDE (cross-modality proof).
- Decision: context = design variables only; **cell type excluded** (data-
  inferred → leakage). Sample-level covariates to be reintroduced into the KG.
- Added: `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
  `docs/AGENT_SESSION_PROMPT.md`, `.github/workflows/ci.yml`.
- Tooling: ruff rule set (E,F,I,UP,B,SIM,C4,RUF) + `ruff format`; mypy with
  pydantic plugin, `src/parce` checked, `parce.tools.*`/`parce.agent.*`
  temporarily exempt (remove on migration). Formatted all files.
- Gates green locally: ruff check, ruff format --check, mypy, 43 unit tests.
- **Next session:** PR 2 (canonical KG schema). No code behavior changed yet;
  `main.py` still runs the old narrative pipeline until PR 3.
