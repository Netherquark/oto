# gfx90c Tensile Port — Knowledge Base (oto)

> Status: **APPROVED (2026-09-13)**.

**Target:** gfx90c — Cezanne APU iGPU, Ryzen 5 PRO 5650U
**ISA:** (9,0,12) — GFX9/GCN5 "Vega 7", NOT RDNA
**Tensile:** v4.44.0 — **only** the tree named by the repo-root `.env` key
`TENSILE_ROOT`:
(pristine upstream + **minimal in-tree gfx90c support**: 3 bookkeeping entries in
`Common.py` + `AsmCaps.py`, landed 2026-09-19)
**Date:** 2026-09-13 (mechanism updated 2026-09-19)
**Numeric source:** `gfx90c_common.PEAK_GFLOPS` — the single source for every peak figure in this ecosystem

This file is the **WHAT** layer of the oto ecosystem: the baseline repository and
code architecture — what Tensile is, what the gfx90c port path is, and what a library
build produces. It deliberately contains no history, no plans, and no measurements.
History lives in `changelog.md`; measurements live in the results pipelines.

Scope of this file (gates satisfied at approval):

- [x] Tensile pipeline and repository topology
- [x] The gfx90c port mechanism (3 minimal in-tree bookkeeping entries)
- [x] Parameter / problem-shape semantics
- [x] Solution-space vocabulary (kernel token glossary)
- [x] Shipped gfx900 footprint (replication target)
- [x] Empirical kernel levers for gfx90c (measured truth)
- [x] Measurement discipline and reporting chain
- [x] Data preservation law
- [x] Glossary

---

## 1. What Is Tensile

> **Tensile** is a benchmark-driven backend library generator for GEMMs and
> GEMM-like / tensor operations. It is the backend library generator of rocBLAS:
> instead of shipping a single kernel per operation, it generates a **library** of
> solution variants and selects among them at dispatch time.

Key properties:

- **Benchmark-driven:** solutions are selected on measured performance; the generator
  builds and benchmarks solution sets per ISA and target feature set.
- **Library, not one-off:** the artifact is a `tensilelibrary` — a family of kernels
  plus dispatch metadata — not a handful of handwritten kernels.
- **Beyond plain GEMM:** generation covers GEMM-like and tensor shapes; the shipped
  footprint (section 6) spans complex, double, half, and int types.

### 1.1 The three-stage pipeline

1. **TensileCreateLibrary** — library generator. Reads `GlobalParameters` plus the
   problem / Exact shapes (`[M,N,B,K(=SizeL)]`) and generates the per-ISA solution set.
2. **TensileBenchmark** — client that compiles the generated solutions and benchmarks
   them. Raw results land in `2_BenchmarkData/*.csv`; the aggregate is `00_Final.csv`.
3. **TensileMergeFiles** — merges per-ISA results and assembles the final library
   artifact (`.dat` / `.co`).

### 1.2 Division of ownership

> Config semantics are **owned by Tensile**. The harness only sets **dtype, shapes,
> NumBenchmarks, ScheduleName**; it does not reach into per-solution scheduling
> internals. The port mechanism (section 3) only makes the ISA exist in Tensile's eyes —
> it does not alter how configs are interpreted.

---

## 2. Repository Topology

**Canonical Tensile root (one path; location from the repo-root `.env` key
`TENSILE_ROOT`):**

That tree is pristine upstream HEAD plus the gfx90c support delta (2 files:
`Tensile/Common.py`, `Tensile/AsmCaps.py` — section 3). The `oto` ecosystem
folder is docs + the new python **driver**. It does not contain Tensile. 

```
<TENSILE_ROOT>/
├── Tensile/bin/Tensile              benchmark CLI  (TENSILE_BIN)
├── Tensile/bin/TensileCreateLibrary library CLI
├── Tensile/                         python package (import Tensile)
├── gfx90c_common.py                 PEAK_GFLOPS authority
├── gfx90c_runs/                     live per-run artifacts
├── gfx90c_results/                  live ledgers (jsonl today; registry.db next)
├── configs/                         vendor YAML problem sets
└── Source/                          host-side dispatch / emitted assembly
```

Invocation (same as the proven suite):

```
PYTHONPATH=<TENSILE_ROOT>:$PYTHONPATH
python3 <TENSILE_ROOT>/Tensile/bin/Tensile --arch gfx90c \
  --assembler … --cxx-compiler … -d 0 <config.yaml> <outdir>
```

`PYTHONPATH` carries only the Tensile package itself.

This project's driver source (outside that tree, still **calls into** it):

- `port_tensile.py` — the oto driver (phases from `phases.yaml`; specification in
  `implementation_plan.md` §The Driver Architecture); plus its modules `registry.py`,
  `report.py`, `analytics.py`, `policy.py`, `scheduler.py`, `agent.py`.
- `gfx90c_common.py` — shared constants and hardware identity (`PEAK_GFLOPS`, rate
  card, dtype tables)
- `all_runs_dataset.py` — aggregation of all run data → `all_runs_dataset.json`
- `make_results_md.py` — DERIVED results blocks for markdown
- `make_report.py` — `gfx90c_report.html` single-file report (inline SVG)
- `auto_retire.py` — retirement automation (retirement logic moves into
  `policy.py` / `agent.py` in the refactor)

The gfx90c delta (the entire change vs upstream — see section 3):

- A 2-file in-tree patch: `Tensile/Common.py` + `Tensile/AsmCaps.py`.

---

## 3. The gfx90c Support Mechanism

The port is **pristine upstream Tensile plus a minimal in-tree bookkeeping patch**,
landed 2026-09-19 on latest `develop_deprecated` HEAD (verified against
`origin/develop_deprecated`).

Three entries, in order:

1. `(9,0,12)` registered in **`SupportedISA`** (`Tensile/Common.py`) — gfx90c now exists
   in the toolchain's default ISA list; `restoreDefaultGlobalParameters()` keeps it.
2. `architectureMap["gfx90c"]` (+ `:xnack+` / `:xnack-`) in `Tensile/Common.py` —
   the arch name resolves to its ISA, feature-capability set, and architecture-family
   entry inside the generator.
3. A real **`(9,0,12)` capabilities entry** in `Tensile/AsmCaps.py` — written from
   scratch from LLVM `FeatureISAVersion9_0_C` (`HasMadMixInsts`; no MFMA / dot /
   dl-insts / VOP2-fmac / WMMA / kernarg-preload). Capability lookups cache on first
   request; this entry is what makes gfx90c supported instead of probed-and-rejected
   at `populateCapabilities` time.

Ordering requirement:

> Config merge happens **after** `populateCapabilities`. Adding gfx90c support at
> config-parse time is therefore too late; the capability entry must already exist in
> source before the config parses. The in-tree patch satisfies this by carrying the
> entry in `AsmCaps` (the ISA list and arch map in `Common`), so every entry point —
> CLI, library generation, benchmarking — sees gfx90c as supported from import.

Consequence:

- `PYTHONPATH` = Tensile package only.
- The entire delta vs upstream is 3 bookkeeping entries across 2 files — revertible
  with `git checkout -- <files>`, and the real capabilities are still derived
  **per-instruction from the assembler** at runtime and verified against the written
  baseline (0 mismatches as of 2026-09-19).

---

## 4. GlobalParameters & Problem Semantics

At generation time, `TensileCreateLibrary` reads `GlobalParameters` (defaults merged
with the config) plus the list of problem shapes (Exact shapes) `[M,N,B,K(=SizeL)]`.

Parameters the harness touches:

- **dtype** — the data-type card (FP16 / BF16 / FP32 / FP64 / INT8 / complex families).
- **Exact shapes** — `[M,N,Batch,SizeL(K)]` rows; dataset convention is `"MxNxB"+SizeL`.
- **ScheduleName** — per-ISA schedule label (`"isa"` vs `"vega10"`; label-level only —
  section 7).
- **NumBenchmarks** — seeds for the median-of-seeds rule (>=3 in production).
- **EnqueuesPerSync / Syncs** — brick sizes: smoke gates use small bricks, production
  cells use large bricks.
- **MergeFiles** — assembly control for `TensileMergeFiles`.

Shape-row semantics:

- Each Exact row is an individual benchmarking **cell**; the same (dtype, shape) across
  configurations is a **shared cell** (glossary).
- The generator treats SizeL as K — the contracted inner dimension — so one lever set
  (section 5) governs every shape row.

Ownership boundary (repeated here for the config reader):

> Tensile owns config semantics. The harness sets only dtype, shapes, NumBenchmarks,
> and ScheduleName. Per-solution spatial knobs (MT/TT/WG/...) are solution vocabulary
> (next section), not harness inputs.

---

## 5. Solution Space: what a "kernel" is

A solution is a **VALU vector kernel** generated per (datatype, contraction pattern).
`HasMFMA = FALSE` on gfx90c: there are no matrix-instruction / microtile solution
forms, and `ScheduleIterAlg` is restricted to **0 / 1**.

Contraction patterns (the four A/B inner-loop layouts the generator schedules on):

- `Ailk_Bjlk`
- `Ailk_Bljk`
- `Alik_Bjlk`
- `Alik_Bljk`

Every shipped family appears once per pattern, so each family is a 4-pattern set.

### 5.1 Token glossary

Decode of a typical solution name `Cijk_Ailk_Bljk_<DT>_<tokens>`:

| Token | Meaning |
|---|---|
| `Cijk` | output layout prefix |
| `SB` `HB` `DB` `I8II` `BBS` | dtype prefix |
| `MT` | MacroTile |
| `TT` | ThreadTile |
| `WG` | WorkGroup |
| `WGM` | WorkGroupMapping |
| `GSU` | GlobalSplitU |
| `VW` / `VWB` | VectorWidth |
| `GLVW` | prefetch family: `PGR` = PrefetchGlobalRead, `PPLR` = PrefetchLocalRead |
| `NLCA` | NumLoadsCoalescedA |
| `EPS` | ExpandPointerSwap |
| `LPA` / `LPB` | LdsPad (A / B) |

Searchable whole-knob list for describing a solution: `MacroTile / ThreadTile /
WorkGroup / GlobalSplitU / DepthU / VectorWidth / PrefetchGlobalRead /
PrefetchLocalRead / WorkGroupMapping / NLCA / EPS`.

### 5.2 Restrictions without MFMA

- `ScheduleIterAlg` only 0/1 (no schedule-iterative matrix-instruction passes).
- No matrix-instruction / microtile forms; every gfx90c solution is a vector kernel.
- gfx900-family tiles are the **prior**, not the payload: ISA900 kernels are **not
  loadable** on gfx90c, so the gfx900 mesh must be **translated**, never copied.

---

## 6. Shipped gfx900 Footprint

> The replication goal (see `mapping.md`): **28 frozen family libraries, 3,066
> kernels** — zero of which are loadable on gfx90c today. That absence is the gap:
> replicate this footprint and produce a `tensilelibrary` that performs all of these
> functions natively on gfx90c (performing better than gfx900 spoofing). No more, no
> less.

28 families = 7 dtype families × 4 contraction patterns (section 5).

Kernel counts per family (total 3,066):

| Family | Kernels |
|---|---|
| CC | 64 |
| DD | 104 |
| ZZ | 26 |
| HH | 314 |
| HH_HPA | 424 |
| HS_HPA | 493 |
| SS | 1,641 |

Character of the mesh:

- **SS 1,641** — big-tile deep-K mesh; the dominant family by far.
- **DD / ZZ** — small U-tiles.
- **HH / HH_HPA / HS_HPA** — 64×64 tiles.
- The mesh spans **459+ size-keys** and is a **defensive** coverage net — it is NOT a
  tuning result.

Translation constraint:

- ISA900 kernels are not loadable on gfx90c, so every family must be re-derived
  natively. The tuning intel carried across is the *lever* knowledge (section 7), not
  the binaries or the per-ISA tiles.

---

## 7. Kernel Levers That Matter on gfx90c

Operational ordering: **coverage first**. Lever selection is subordinate to covering
every function of the 28-family footprint (section 6). The levers below are the
measured truths (frozen prior conclusions in `prior_INSIGHTS_CAVEMAN_ULTRA.md`
§5.1) that make coverage cheap and correct on gfx90c.

Rate card (peaks @ 1800 MHz; single source `gfx90c_common.PEAK_GFLOPS`; ceiling
authority `gfx90c_theoretical_limits.md`):

- FP32 — 1613 GFLOPS (448 FP32 lanes)
- FP16 — 3226 GFLOPS (dual-issue `v_pk_fma_f16`)
- BF16 — 1613 GFLOPS (single-rate)
- INT8 — 1613 GFLOPS (single-rate — NO dp4a dual-rate)
- FP64 — 101 GFLOPS (VALU 1/16)

Per-datatype levers (measured):

- **FP32 large square** — `MT96x96x16` + `NLCA3`; 1536³–4096³ ≈ 890–960; best
  1118.7 @ 1024³ (p27); `MT128x128x16` also viable.
- **FP32 odd shapes** — `MT96x96x16` + `TT6_6` + `NLCA3`.
- **FP32 decode GEMV** — `VW1` + tiny TT: `MT8x32x32` / `TT1_4`, `WG8_8_4` `WGM8`.
- **FP16 large** — `MT128x128x16` + `NLCA1` + `PGR0`; best 2492.1 @ 4096³.
- **FP16 GEMV** — `MT16x64x32` / `TT2_8`.
- **BF16** — `MT128x64x8` or `MT128x128x16`; best 1108.5 @ 2048³.
- **FP64** — `MT32x32x16` / `MT64x64x8` AMAS; 98.6 @ 1024³ = 98% of peak; saturated.
- **INT8** — `MT128x128x16` single-rate; best 881.2 @ 2048³; int8 1024³ is a +18.3% win
  at the `MT128x128x16` regime.

Grid sizing:

- **GSU (GlobalSplitU)** is used only to fill the 7-CU grid: 256³ → GSU8; 512³ →
  GSU2; 128×128×2048 → GSU1. It is NOT a general tuning knob.

Schedule label:

- **ScheduleName** `"isa"` vs `"vega10"` — label-level only; no performance effect.

---

## 8. Measurement Science

- Winner rule: **median-of-seeds**, `NumBenchmarks >= 3` for production cells.
- **Ruler / throttle:** comparisons are ruler-throttle adjusted per (datatype,
  bound_class). Bound classes are **ALU** and **DDR**; each class calibrates on its own
  ruler control.
- **Missing controls are reported, never inferred** — a comparison without its ruler is
  flagged absent, not filled in.
- **Cross-run envelope:** raw spread ±23–31% ALU / ±6–19% DDR, driven by shared
  thermals on the APU. This is why cross-run best-versus-best is forbidden (below).
- **Ties:** ±5% = parity, not win.
- **Telemetry:** sysfs contract; `logs/telemetry.csv` keeps its header in-file so the
  log is self-describing.
- **Data law:** section 10 governs everything that touches the dataset.

Measurement no-go's:

- Best-of-runs vs best-of-history comparisons across runs.
- Inferring a missing ruler control.
- Scoring a ±5% tie as a win.
- Reading a winner from a single-shot seed run.

---

## 9. Reporting Toolchain

Pipeline (in order):

1. `all_runs_dataset.py` — aggregates `run_*/` data → `all_runs_dataset.json`.
2. `make_results_md.py` — renders **DERIVED** results blocks from the dataset.
3. `make_report.py` — builds `gfx90c_report.html` (single file).

Acceptance ceilings: per-family bars come from `gfx90c_theoretical_limits.md`
(§5), derived from rocminfo + first-party ISA verification — do not use the raw PEAK
table here when scoring "approach the theoretical limit".

Data invariants every consumer relies on:

- `2_BenchmarkData` CSVs (plus `00_Final.csv`) — the raw benchmark bricks.
- `gfx90c_results/registry.db` — the shared append-only ledger (`records` INSERT-only).
- Run-local artifacts under `gfx90c_runs/run_YYYYMMDD_HHMMSS/` — configs, CSVs, telemetry.
- `logs/telemetry.csv` — header-in-file (self-describing, no sidecar).
- Frozen `gfx90c_results/{experiment_db,benchmark_registry}.jsonl` — **frozen, still protected**; never rewritten. New evidence goes to SQLite.
- `configs/phaseN_*.yaml` — fingerprints (`fp`); a changed fingerprint is a new attempt.
- `run_YYYYMMDD_HHMMSS/` — era-named run directories.
- `phases.yaml` — the data-only **manifest** (source of phase definitions). Not replaced by a DB table.

---

## 10. Data Preservation Law (append-only — canonical)

> **⛧ NEVER DELETE, OVERWRITE, OR REWRITE benchmark data.** This law is the only
> legally-canonical statement of it. Every other doc that mentions the data law points
> here instead of restating it (avoids drift).

The law holds for every producer of project data (driver, report tooling, analysis
scripts, the operator) and for every consumer (report renderers, verdict code, the
DB). A violating session is a project-blocking error.

### 10.1 What is protected

Every stream of benchmark evidence, past and future:

- `gfx90c_results/registry.db` table `records` — the shared ledger (INSERT-only).
- `gfx90c_runs/run_YYYYMMDD_HHMMSS/**` — per-run artifacts: `configs/phase*.yaml`,
  `phase*/2_BenchmarkData/*.csv`, `00_Final.csv`, `logs/telemetry.csv`.
- Frozen `gfx90c_results/{experiment_db,benchmark_registry}.jsonl` ledgers. Remain
  **in place**; never rewritten, never deleted, never "migrated in place". Readers
  may ingest them into SQLite as **new** `records` rows (copy-forward), never
  truncate the jsonl.
- `results.md` — its `<!-- DERIVED:* -->` blocks *and* its hand prose.
- `gfx90c_report.html` — regenerated from data, never hand-repaired.
- Corrupt jsonl records from the frozen set remain **in place** (triage: readers
  must tolerate and mark, never repair the file by deleting the row).

### 10.2 Append-only mechanics (SQLite)

`fcntl.flock` + JSONL is **no longer a write path**. Persistence uses stdlib
`sqlite3` (`gfx90c_results/registry.db`, WAL). The law is unchanged: never delete,
overwrite, or rewrite **benchmark evidence**.

- **`records`**: one `append_record()` / `INSERT`. Payload built with
  `json.dumps(dict)` stored in the `data` column — never printf-`%s` interpolation,
  never `UPDATE`/`DELETE` of a `records` row. No sibling `.lock` files.
- **Single-writer process** remains the concurrency model (the driver is one
  process). WAL is for crash safety and readers, not a license for multi-writer
  fork-lock.
- **`runs`**: operational checkpoint (status / started_at / completed_at). Status
  `UPDATE` is allowed. This table is **not** benchmark evidence.
- **`phases.yaml` is the manifest.** A SQLite `phases` table, if present, is at
  most an index/cache. It must not replace the YAML file, must not UNIQUE-drop
  new attempts, and must not become the `--auto` feed target. Harvest still
  **appends rows to `phases.yaml`**.
- **A changed fingerprint is a NEW attempt.** Old attempt + data stay untouched.
- Retirement **appends** a `retire` record (or equivalent `record_type`) that
  marks exclusion from scoring — it never removes rows, and a retired record is
  always reversible by a later append.
- Phase-number reservations and run-order are asserted (order self-check) so a
  run can never silently skip or reorder intended work.
- Stats/HTML pipeline (`all_runs_dataset.py` → …) still consumes run dirs + CSV.
  Until that pipeline reads SQLite, the driver may **also** append a jsonl
  *export* of new `records` (dual-write). Dual-write is export, not a second
  source of truth. Canonical ledger = `records`.

### 10.3 Derived artifacts

- `make_results_md.py` rewrites **only** the `<!-- DERIVED:* -->` marker blocks; hand
  prose outside the markers is preserved verbatim by the renderer.
- `gfx90c_report.html` is regenerated wholesale from the dataset; never hand-edited.
- The single peak authority is `gfx90c_common.PEAK_GFLOPS` (see section 7); derived
  prose that contradicts it is regenerated, not hand-patched.

### 10.4 Consequences of a change

- New measurement → **append** new records and a new run directory; re-render DERIVED
  blocks by regenerating, never by hand-tuning numbers.
- Methodology or math change → revalidate derived conclusions; the derived output may
  change, but the underlying data rows do not.

---

## 11. Glossary

- **run** — one execution of the driver over a set of phases (`port_tensile.py
  [--phases ...]`); captured in an era-named `run_YYYYMMDD_HHMMSS/` directory.
- **phase** — one manifest row of the driver (`phases.yaml`); phase 1 is
  first-ever-run-only by contract, and phase-number gaps are reserved (see
  `changelog.md`).
- **fp (fingerprint)** — canonical hash of a config (`configs/phaseN_*.yaml`); a change
  of fp means a new attempt, never an in-place edit.
- **cell** — one (shape × dtype × config) benchmark unit; the atomic row of the dataset.
- **ruler control** — the throttle-adjusted reference measurement for a (datatype,
  bound_class); rulers calibrate all comparisons within a run.
- **shared cell** — a cell measured for more than one configuration in the same run, so
  they compare under one ruler.
- **tielayer** — the classification layer applying the ±5% tie rule (parity, not win).
- **era** — suite era, named by first-run date; gates such as Phase-0 10/10 are per-era.
- **PROTECT set** — the set of cells/records protected from modification or retirement;
  the append-only law applies to these absolutely.
- **RED list** — the retirement list; entries marked retired are excluded from win/loss
  scoring.
- **EnqueuesPerSync / Syncs** — brick sizes; small for smoke gates, large for
  production benchmarking (smoke-vs-production note, section 4).
- **tensilelibrary** — the assembled library artifact (`.dat` / `.co`) plus dispatch
  metadata that Tensile/rocBLAS select from.

---

Related documents: `changelog.md` (the evolution narrative), `gfx90c_theoretical_limits.md`
(ceiling authority), `mapping.md` (footprint contract), `prior_INSIGHTS_CAVEMAN_ULTRA.md`
/ `prior_RESEARCH_ARCHIVE.md` (frozen prior conclusions).