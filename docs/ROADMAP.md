# PARCE Roadmap

Living plan. **Each session reads this to find its task and updates it before
finishing.** See [AGENT_SESSION_PROMPT.md](AGENT_SESSION_PROMPT.md) for the
protocol and [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

---

## ▶ Next up

**PR 3 — Source-adapter interface + cheap CELLxGENE adapter.** Define
`SourceAdapter` / `Normalizer` protocols in `sources/` + `normalize/`. Refactor
CELLxGENE into a deterministic adapter. **Remove the LLM/Azure narrative path
entirely** (delete `agent/prompts.py` narrative role, `models/narrative.py`, the
narrative `NarrativeOutput` schema in `models/graph_schema.py`, and step 2 of
`main.py` — `_build_narrative_prompt`, the agent call, and the now-unused
`narrative` variable). Drop cell-type extraction. Remove the `parce.tools.*`
mypy exemption as those modules move under `sources/`.

---

## PR sequence

Each PR is one branch, one focused scope, green CI, and a roadmap update.

- [x] **PR 1 — Foundations & tooling.** CLAUDE.md, docs (architecture, roadmap,
  session prompt), GitHub Actions CI (ruff, mypy, pytest), ruff rule set + mypy
  config in `pyproject.toml`, code formatted to baseline. No behavior change.
- [x] **PR 2 — Canonical KG schema.** Source-agnostic nodes/edges; add
  `SampleNode` with design covariates; drop `experimental_narrative` and
  `CellType`. Migrate builder + tests.
- [ ] **PR 3 — Source-adapter interface + cheap CELLxGENE adapter.** Define
  `SourceAdapter` / `Normalizer` protocols in `sources/` + `normalize/`. Refactor
  CELLxGENE into a deterministic adapter. **Remove the LLM/Azure narrative path
  entirely** (delete `agent/prompts.py` narrative role, `models/narrative.py`,
  the `NarrativeOutput` schema, and the step-2 block in `main.py`). Drop
  cell-type extraction. Remove the `parce.tools.*` mypy exemption as those
  modules move under `sources/`. *(Next up.)*
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

### 2026-06-23 — PR 2: Canonical KG schema

- Branch `pr2-canonical-kg-schema` off `main`.
- Rewrote `models/graph_schema.py` to the source-agnostic canonical schema:
  - `PublicationNode` → **`StudyNode`** (`study_id`, `title`, `source`,
    `modality`); dropped `abstract` and `experimental_narrative`. Raw free text
    belongs to the future `RawRecord`, not the canonical node.
  - `DatasetNode`: `uri`→`data_uri`, `modality`→`assay`; no parent-study field.
  - **`SampleNode`** added (design covariates only: `condition`, `perturbation`,
    `timepoint`, `subject`, `organism`, `data_uri`; all optional). Not populated
    by the CELLxGENE path yet (Census is dataset-level — see ARCHITECTURE §6).
  - `EntityType`: **`CellType` removed** (data-inferred → leakage).
  - `KnowledgeGraphOutput.publications` → `studies`; added `samples`.
- Migrated `graph/builder.py`: signature is now
  `build_knowledge_graph(paper_data, cellxgene_data)` (no `narrative`); emits
  `StudyNode`/`DatasetNode`; ignores input `cell_types`; tissue→`HAS_TISSUE`,
  disease→`HAS_CONDITION`, assay→`MEASURED_WITH`, study→species `STUDIES`.
  `source="CELLxGENE"`, study `modality="scRNA-seq"` (constants for this path).
- Decision: **containment is edge-only.** `DatasetNode` does not store its parent
  `study_id`; the `EXTRACTED_FROM` edge is the single source of truth (avoids a
  denormalized FK that can drift). Recorded in ARCHITECTURE §4.
- `main.py`: step 3 drops the `narrative` arg; summary prints `Studies`/`Samples`.
  **Deferred to PR 3 (not done here):** step 2 still generates the narrative via
  Azure, but its output is now discarded (a comment marks this). `NarrativeOutput`
  stays in `graph_schema.py` and `_build_narrative_prompt` still references
  `cell_types` — both are part of the narrative path PR 3 deletes wholesale.
- Updated tests: `test_graph_schema.py`, `test_builder.py`, `test_orchestration.py`
  (asserts `studies`/`study_id`, no narrative, cell-type exclusion, sample
  covariates, tissue dedup). `models/narrative.py` + `test_models.py` untouched
  (legacy GEO agent schema; PR 3/PR 5 territory).
- Gates green locally (incl. hermetic run with no `.env`): ruff check, ruff
  format --check, mypy (16 files), **52 unit tests** pass. No dep changes.
- **Next session:** PR 3 (source-adapter interface + rip out the narrative path).

### 2026-06-23 — Ontology grounding (docs)
- Decision: every experiment facet binds to one designated ontology (EFO assay,
  UBERON tissue, MONDO disease, NCBITaxon organism, ChEBI/gene-ID perturbation,
  PSI-MS for MS proteomics, EDAM data format). Registry will live in
  `parce/ontology/`.
- Decision: **no free-text `modality` long-term.** Store `assay` (EFO term ID) +
  a coarse `molecular_layer` enum derived by walking EFO `is-a` ancestors — both
  controlled. PR 2 shipped with a `modality` field; this refinement now lands in
  **PR 4** (see ARCHITECTURE §4–5).
- Decision: resolve term IDs at runtime via OLS4 (+ text2term/Zooma, LLM
  fallback); never hardcode IDs. Follow SDRF/MAGE-TAB conventions for the record.
- Added ARCHITECTURE §5 (Ontology grounding; later sections renumbered) and
  sharpened ROADMAP PR 4 (registry + lineage derivation + anchor-set open
  question). Docs only, no code change.
- Authored on the foundations branch and merged on top of PR 2 / PR 3.
  **Next up: PR 3.**

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
