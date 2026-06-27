# PARCE Roadmap

Living plan. **Each session reads this to find its task and updates it before
finishing.** See [AGENT_SESSION_PROMPT.md](AGENT_SESSION_PROMPT.md) for the
protocol and [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

---

## ▶ Next up

**PR 5 — GEO extraction agent (vertical slice).** First source whose metadata is
*unstructured* free text, so the first to use the LLM. Add a GEO adapter
(NCBI E-utilities / GEOparse) emitting a `RawRecord`, and an **Azure extraction
normalizer** that fills the canonical schema via `response_format` (structured
output only — never prose). Extract sample-level **design** covariates from
`characteristics_ch1` (`condition`, `perturbation`, `timepoint`, `subject`,
`organism`) into `SampleNode`s — never data-inferred annotations. Ground the
extracted free-text facets through the **existing `OntologyResolver`** (organism
→ NCBITaxon, assay → EFO + `molecular_layer`, tissue → UBERON, disease → MONDO),
and **supply the agent as the resolver's LLM-fallback callback** for strings OLS
can't map (the hook already exists, default off). Mark live tests
`@pytest.mark.integration`; keep unit tests offline by mocking the Azure client.
**Remove the `parce.agent.*` mypy exemption** in `pyproject.toml` once the agent
moves to the normalizer interface. **Blocker risk:** needs Azure creds + an
`az login` session; if absent, build/unit-test the deterministic scaffolding and
log the integration boundary as a blocker rather than working around it.

---

## PR sequence

Each PR is one branch, one focused scope, green CI, and a roadmap update.

- [x] **PR 1 — Foundations & tooling.** CLAUDE.md, docs (architecture, roadmap,
  session prompt), GitHub Actions CI (ruff, mypy, pytest), ruff rule set + mypy
  config in `pyproject.toml`, code formatted to baseline. No behavior change.
- [x] **PR 2 — Canonical KG schema.** Source-agnostic nodes/edges; add
  `SampleNode` with design covariates; drop `experimental_narrative` and
  `CellType`. Migrate builder + tests.
- [x] **PR 3 — Source-adapter interface + cheap CELLxGENE adapter.** Defined
  `SourceAdapter` / `Normalizer` protocols in `sources/` + `normalize/`. Refactored
  CELLxGENE into a deterministic adapter + normalizer. **Removed the LLM/Azure
  narrative path entirely** (deleted `agent/curator.py`, `agent/prompts.py`,
  `models/narrative.py`, the `NarrativeOutput` schema, and the step-2 block in
  `main.py`). Dropped cell-type extraction. Removed the `parce.tools.*` mypy
  exemption as those modules moved under `sources/`.
- [x] **PR 4 — Ontology resolver (stage + organism wiring).** Shared `ontology/`
  stage (see ARCHITECTURE §5): pinned the **facet → ontology registry** constant
  (EFO/OBI/PSI-MS, UBERON, MONDO, NCBITaxon, ChEBI, EDAM); `OlsClient` (OLS4 REST,
  retry-wrapped, injectable); on-disk `ResolutionCache` (negative results cached);
  `OntologyResolver` (cache → OLS exact-then-fuzzy → pluggable LLM-fallback hook,
  default off); and the **`molecular_layer` derivation** (EFO `is-a` ancestor walk
  → pinned anchor labels; no-anchor default `UNKNOWN`). Replaced the hardcoded
  `_ORGANISM_ONTOLOGY` map in `normalize/cellxgene.py` with runtime NCBITaxon
  resolution. **Decided: OLS4-only** for now (text2term/Zooma deferred to GEO/PR 5
  — CELLxGENE ships IDs, only organism free-text needed grounding). IDs resolved
  at runtime; none hardcoded. *Split from the original PR 4: the schema change
  (store the EFO assay term + `molecular_layer`) became PR 4b.*
- [x] **PR 4b — Schema refinement.** Replaced free-text `modality` with an EFO
  `assay` term ID + a stored `molecular_layer` enum on `StudyNode`/`DatasetNode`;
  wired assay grounding (taken from Census's already-grounded payload) + layer
  derivation into `CellxgeneNormalizer` via a new `OntologyService` contract;
  migrated the schema and all tests. **Switched `molecular_layer` matching from
  exact EFO labels to ordered substring keywords** after validating against live
  EFO (the 10x family never reaches `RNA assay`); ambiguous lineages (bare
  mass-spec, multi-omic terms) stay `UNKNOWN` by design.
- [ ] **PR 5 — GEO extraction agent (vertical slice).** GEO adapter
  (E-utilities/GEOparse) + Azure extraction normalizer emitting the canonical
  schema via `response_format`; extract sample covariates from
  `characteristics_ch1`. Integration test (marked). This is the agent's real
  job; remove the `parce.agent.*` mypy exemption. *(Next up — see top of file.)*
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

### 2026-06-26 — PR 4b: Schema refinement (EFO assay term + stored molecular_layer)

- Branch `pr4b-schema-refinement` off `main` (35a28ce, the PR 4 merge). Note: the
  scheduled session started on a stale worktree whose `main` predated the PR 4
  merge; `gh` showed PR #7 already MERGED, so PR 4 was done and **PR 4b was the
  real ▶ Next up**. Re-based onto `origin/main` before starting.
- **Schema (`models/graph_schema.py`).** Dropped `StudyNode.modality`. Both
  `StudyNode` and `DatasetNode` now carry `assay` (EFO term ID, required) +
  `molecular_layer` (`MolecularLayer`, default `UNKNOWN`). `DatasetNode.assay`
  changed meaning from free-text name → grounded EFO ID.
- **Normalizer (`normalize/cellxgene.py`).** Per dataset: pick the grounded EFO
  assay ID from Census's payload (`ontology_summary.assays`, matched to the
  dominant `modality` *name*) and derive `molecular_layer` from it; `StudyNode`
  built at the end with the **most-frequent** dataset assay as its representative
  + that assay's layer. Layer derivation memoised per assay ID; only `EFO:` IDs
  are walked (an ungrounded `unknown` assay → `UNKNOWN`, no network call).
- **Decision — assay taken from payload, not re-resolved.** CELLxGENE ships the
  EFO assay ID; Census is authoritative for its own data and re-resolving via OLS
  could drift, so the resolver is used *only* for the lineage walk. Free-text
  sources (GEO/PRIDE) will resolve the assay string first. (ARCHITECTURE §5.)
- **Decision — `molecular_layer` matching: exact labels → substring keywords.**
  Probing live EFO exposed the PR 4 gotcha for real: `EFO:0009922` (10x 3' v3, the
  bulk of CELLxGENE) never reaches `RNA assay` — it sits under `…transcription
  profiling`/`library preparation`; ATAC/ChIP/methylation/WGS all collapse to a
  generic `DNA assay` ancestor. Rewrote `ontology/layers.py` to ordered,
  case-insensitive **substring keywords** (transcriptome/epigenome/proteome/
  metabolome before the broad GENOME `DNA` signals), validated against live EFO.
  Bare mass-spec and multi-omic terms stay `UNKNOWN` by design (genuinely
  ambiguous). The marked integration test now asserts exact layers (10x + scRNA →
  TRANSCRIPTOME, ATAC → EPIGENOME) and **passed live** this session.
- **New contract `OntologyService`** (`ontology/base.py`, exported) = `TermResolver`
  + `molecular_layer`; the normalizer depends on it so offline fakes inject both
  methods. `base.py` now imports `MolecularLayer` (models is a leaf; no cycle).
- **Gates green incl. hermetic no-`.env` run:** ruff check, ruff format --check
  (40 files), mypy (24 files), **133 unit tests**. Live OLS integration suite (6)
  also passed. No dep changes; no new mypy exemptions.
- **Next session:** PR 5 (GEO extraction agent) — first LLM/Azure source; needs
  credentials. Wire the GEO free-text facets through the existing resolver and
  supply the agent as its LLM-fallback callback. If Azure creds are missing, stop
  at the integration boundary and log the blocker.

### 2026-06-25 — PR 4: Ontology resolver (stage + organism wiring)

- Branch `pr4-ontology-resolver` off `main` (64ed4f4).
- **Split decision.** The roadmap's PR 4 bundled the resolver stage *and* the
  schema change (free-text `modality` → EFO `assay` term + stored
  `molecular_layer`). Shipped the stage + organism wiring here; the schema
  migration is now **PR 4b** (new ▶ Next up). Rationale: the stage is a coherent,
  fully-tested unit; the schema swap touches the canonical models + every
  CELLxGENE test and is cleaner as its own focused PR.
- **New package `src/parce/ontology/`** (stable core, fully mypy-checked):
  - `registry.py` — `Facet` enum + `FACET_ONTOLOGY` constant. Pins *ontologies,
    not IDs*: EFO (assay; fallbacks OBI then PSI-MS), UBERON, MONDO, NCBITaxon,
    ChEBI, EDAM. `FacetBinding.ontologies()` gives primary→fallback order.
  - `ols.py` — `OlsClient` for OLS4 REST: `search` (free text → class hits) and
    `ancestors` (hierarchical/`is-a`). `http` getter is injectable (offline
    tests); requests wrapped in `sources._retry.with_retries`. `obo_id_to_iri`
    builds EFO + generic OBO-PURL IRIs and the path is double-URL-encoded.
  - `cache.py` — `ResolutionCache`, JSON-on-disk, atomic writes, lock-guarded.
    **Caches negative results** (a *miss* vs a cached-`None` are distinguished via
    `get`'s first return value) so unresolvable strings aren't re-queried.
  - `layers.py` — `derive_molecular_layer(ancestor_labels)`: pure function
    matching EFO ancestor **labels** (not IDs) against a pinned anchor set;
    most-specific-first; no-anchor default `MolecularLayer.UNKNOWN`.
  - `resolver.py` — `OntologyResolver`: `resolve_term(text, facet)` (cache → OLS
    exact-then-fuzzy across the facet's ontologies → optional LLM fallback) and
    `molecular_layer(assay_id, assay_label=None)`. All collaborators injectable;
    default cache is lazy so construction touches neither disk nor network.
  - `base.py` — `ResolvedTerm` value type + the narrow `TermResolver` Protocol
    normalizers depend on.
- **`MolecularLayer` StrEnum added to `models/graph_schema.py`** (its home, since
  `models` depends on nothing and it becomes a node field in PR 4b). Not yet a
  stored field anywhere.
- **Normalizer wired:** `CellxgeneNormalizer(resolver=...)` now grounds the bare
  organism string to NCBITaxon via the resolver (replacing `_ORGANISM_ONTOLOGY`).
  Tissue/disease/assay still use the IDs Census already ships — only organism was
  free text. An organism that fails to resolve is **skipped** (no ungrounded node
  emitted), logged at WARNING.
- **Decisions / rationale:**
  - **OLS4-only** (open question §7 resolved): text2term/Zooma deferred to GEO
    (PR 5), where the messy `characteristics_ch1` strings actually appear.
  - **LLM fallback is a pluggable `Callable`, default `None`** — keeps `ontology`
    free of any `parce.agent`/Azure import (dependency direction preserved); PR 5
    wires the extraction agent in as the callback.
  - **Anchor set is keyed by EFO label, not term ID** (honours "pin
    ontologies/anchors, not IDs"). **PROVISIONAL** — unvalidated against live EFO;
    `tests/test_ontology_integration.py` (marked, live OLS) is the validation
    harness. PR 4b must run it and correct labels, else assays derive `UNKNOWN`.
  - **`ontology` reuses `sources._retry`** (leaf util, no cycle) per CLAUDE.md.
  - Resolver config (OLS base URL, cache dir) is constructor params, **not**
    `Settings` — avoids the unit-test `Settings()` hermeticity trap; could move to
    Settings later.
- **Tests:** offline unit suites for registry / cache / OLS (fake HTTP getter) /
  layers / resolver (fake client + real cache on tmp_path); `test_normalize.py`
  and `test_orchestration.py` inject a fake resolver so they stay offline. New
  marked integration test for live OLS (organism exact; molecular_layer plumbing).
- **mypy:** no new exemptions; `parce.agent.*` exemption stays (PR 5). 24 source
  files checked, clean.
- **Gates green, incl. hermetic run (worktree has no `.env`):** ruff check,
  ruff format --check (40 files), mypy, **121 unit tests** (was 47+retry). No dep
  changes (stdlib + `requests`), so no `uv.lock` change.
- **Next session:** PR 4b (schema refinement) — and validate the provisional
  `molecular_layer` anchors against live EFO first.

### 2026-06-24 — Generic retry helper (resilience follow-up to PR 3)

- Branch `add-generic-retry-helper`. Not a roadmap PR; **closes the retry
  follow-up flagged in the PR 3 entry below.** Next up stays PR 4. (Authored
  before PR 3 merged, then merged on top of it — adapters now live in `sources/`.)
- Problem: PR 3 removed the Azure-keyed `_is_transient`/`_backoff_delay` helpers
  from `main.py` along with the LLM call (their only caller), leaving the
  CELLxGENE/EuropePMC network IO with no retry/backoff.
- Added `src/parce/sources/_retry.py`: generic, dependency-neutral
  `with_retries(func, ...)` + `is_transient(exc)` (exponential backoff, full
  jitter); mypy-checked stable core, reusable by GEO (PR 5) / PRIDE (PR 7).
- Transient = stdlib `TimeoutError`/`ConnectionError`/`OSError`, `requests`
  connection/timeout errors, and `requests` HTTPError with 429/5xx. **Gotcha
  recorded:** every `requests` exception subclasses `OSError`, so requests
  errors are classified *first* — otherwise a 404 / malformed-URL would be
  wrongly retried.
- Wired into `sources/cellxgene.py` (`open_soma`, datasets table read,
  `get_obs`, `get_source_h5ad_uri`) and `sources/publication.py`
  (`fetch_paper_metadata` — `requests.get` + `raise_for_status` wrapped together
  so 429/5xx actually retry).
- Tests: `tests/test_retry.py` (classification + retry/exhaustion, sleep
  patched) and `tests/test_ncbi_fetcher.py` (offline 503 / conn-error → success
  wiring). Updated CLAUDE.md resilience reference to point at `sources/_retry.py`.
- Gates green incl. hermetic no-`.env` run: ruff, ruff format, mypy, unit tests.

### 2026-06-24 — PR 3: Source-adapter interface + CELLxGENE adapter

- Branch `pr3-source-adapter-interface` off `main` (69d1f68).
- **New contracts.** `models/raw_record.py` adds `RawRecord` (source-shaped:
  `source`, `study_id`, `title`, free-form `payload`) — the boundary object
  between adapters and normalizers. `sources/base.py` defines the `SourceAdapter`
  Protocol (`source_name`, `discover(query) -> [ref]`, `fetch(ref) -> RawRecord`);
  `normalize/base.py` defines the `Normalizer` Protocol
  (`normalize(record) -> KnowledgeGraphOutput`). Both `@runtime_checkable`.
- **CELLxGENE migrated to a deterministic adapter + normalizer:**
  - `tools/cellxgene_fetcher.py` → `sources/cellxgene.py` (`CellxgeneAdapter` +
    the `fetch_cellxgene_datasets` core fn). **Cell-type extraction dropped**: the
    `cell_type*` Census columns and the `cell_types` summary key are gone (reading
    a data-inferred annotation is leakage even before it hits the graph).
  - `tools/ncbi_fetcher.py` → `sources/publication.py` (`fetch_paper_metadata`,
    EuropePMC). The adapter's `fetch` gathers the publication title here because
    Census exposes dataset titles + DOI but not the publication title.
  - `graph/builder.py` → `normalize/cellxgene.py` (`CellxgeneNormalizer`). It now
    reads `record.source`/`title`/`payload` instead of taking a hardcoded source.
  - The `@tool`-decorated wrappers (`fetch_cellxgene_data`, `fetch_paper_context`,
    `fetch_geo_metadata`) were vestigial from the agent-tool-calling era and are
    deleted. The whole `tools/` package and the GEO stub are removed.
- **Narrative/LLM path removed entirely:** deleted `agent/curator.py`,
  `agent/prompts.py`, `models/narrative.py` (and `test_models.py`), and the
  `NarrativeOutput` schema. `main.py` is now deterministic and **synchronous**:
  `discover → fetch → normalize → write`. (PR 5 reintroduces async + the agent.)
- Decisions (rationale):
  - **Per-study assembly is the Normalizer's job; `graph/` is reserved for the
    PR 6 cross-source merger.** Matches ARCHITECTURE §3's split. `graph/__init__.py`
    and `agent/__init__.py` are kept as documented placeholders.
  - **Organism→NCBITaxon map (`_ORGANISM_ONTOLOGY`) lives in the normalizer, not
    the adapter.** The adapter emits the raw organism string; string→ID mapping is
    normalization and becomes the PR 4 OntologyResolver's job.
  - **`discover` is the identity on a DOI for CELLxGENE** (a collection = a DOI).
    Keyword collection search is backlog.
  - **Azure-coupled retry helpers removed from `main.py`** with the LLM call (their
    only caller). CELLxGENE/EuropePMC fetches currently have no retry wrapper —
    see follow-up below. CLAUDE.md still references "helpers in `main.py`"; left as
    is since PR 5 reintroduces retry infra for the agent.
- **mypy:** removed the `parce.tools.*` exemption (modules migrated + now fully
  type-checked); `parce.agent.*` exemption stays for PR 5. mypy checks 16 files.
- **Gates green locally, incl. hermetic run with `.env` moved aside:** ruff check,
  ruff format --check (24 files), mypy, **47 unit tests**. No dep changes; the
  `agent-framework`/`azure-*` deps stay (PR 5 needs them).
- **Follow-up for a later session:** wire bounded-retry/backoff into the source
  adapters' network calls (Census, EuropePMC) — resilience regressed when the
  Azure-only retry helpers were removed.
- **Next session:** PR 4 (ontology resolver). First integration point: replace
  `_ORGANISM_ONTOLOGY` in `normalize/cellxgene.py`.

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
