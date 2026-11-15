# gfx90c Tensile Port — Knowledge Base (oto)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


> **GOLDEN EXAMPLE (gfx90c) — do not edit for a new device; copy the template instead.**

> **gfx90c-specific.** The generic per-device knowledge-base template
> lives in `docs/gfx90c/knowledge_base.md`; this file is the gfx90c golden
> example of how to derive one.

> Status: **APPROVED (2026-09-13)**.

**Era note (2026-11-15).** This file is the port's architecture snapshot as approved
2026-09-13 (its mechanism section was updated 2026-09-19). The **toolchain moved
on 2026-11-14** — the live baseline is the rocm-libraries nightly SDK, not the
v4.44 `develop_deprecated` tree this snapshot documents (`docs/gfx90c/gfx90c_tuning_guide.md`
§12 has the current baseline). This file is kept append-only by the data-preservation
law (§10): stale sections are annotated, never rewritten. Where a table was owned by
another doc, that doc now holds the only copy and this file points at it.

**Target:** gfx90c — Cezanne APU iGPU, Ryzen 5 PRO 5650U
**ISA:** (9,0,12) — GFX9/GCN5 "Vega 7", NOT RDNA
**Tensile:** v4.44.0 — **only** the tree named by the repo-root `.env` key
`TENSILE_ROOT`:
(tracked in-tree checkout holding the **minimal native gfx90c support**: the 2-file
`Common.py` + `AsmCaps.py` patch, landed 2026-09-19 — not pristine, no shim)
**Date:** 2026-09-13 (mechanism updated 2026-09-19; toolchain era note 2026-11-15)
**Numeric source:** `oto.device.loader.current_profile().peak_gflops` — the single source for every peak figure in this ecosystem

This file is the **WHAT** layer of the oto ecosystem: the baseline repository and
code architecture — what Tensile is, what the gfx90c port path is, and what a library
build produces. It deliberately contains no history, no plans, and no measurements.
History lives in `docs/changelog.md`; measurements live in the results pipelines.

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
├── oto/device/loader.py             PEAK_GFLOPS authority (via profiles/gfx90c.json)
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

- `python3 -m oto` (repo root `bin/oto`) — the oto driver (phases from `phases.yaml`; specification in
  `docs/developer/invariants.md` §The Driver Architecture); plus its modules `oto/ledger/registry.py`,
  `oto/metrics/acceptance_report.py`, `oto/metrics/benchmark_analytics.py`, `oto/metrics/cell_policy.py`, `oto/tensile/candidate.py`, `oto/ledger/convergence_agent.py`,
  `oto/metrics/telemetry.py` (run-wide sysfs sampler), `oto/tensile/shipped_floor.py` (gfx900 dat parser +
  reference-floor chain).
- `oto/device/loader.py` — device profile loader + canonical accessors (profile tables via `current_profile()`)
  card, dtype tables)
- `oto/metrics/acceptance_report.py` — acceptance reporting → `gfx90c_results/acceptance_report.json/.html`
  (single-file HTML dashboard; inline SVG/CSS, Carbon design language)
- `oto/ledger/registry.py` — append-only SQLite registry (`gfx90c_results/registry.db`, WAL)
- `oto/metrics/benchmark_analytics.py` — per-cell analytics, native-vs-spoof deltas, cell-status classification (RED = missing, ORANGE = below ceiling)

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

> The replication goal (see `docs/developer/invariants.md`): **28 frozen family libraries, 2,285
> distinct shipped kernels** — zero of which are loadable on gfx90c today. That absence is the gap:
> replicate this footprint and produce a `tensilelibrary` that performs all of these
> functions natively on gfx90c (performing better than gfx900 spoofing). No more, no
> less.

28 families = 7 dtype families × 4 contraction patterns (section 5).

Kernel counts per family — canonical table in `docs/developer/invariants.md` §2
(same total 2,285; the earlier 3,066 was per-file token counting). This file does
not restate the split, so it cannot drift.

Character of the mesh:

- **SS 959** — big-tile deep-K mesh; the dominant family by far.
- **DD / ZZ** — small U-tiles.
- **HH / HH_HPA / HS_HPA** — 64×64 tiles.
- The mesh spans **459+ size-keys** and is a **defensive** coverage net — it is NOT a
  tuning result.

Translation constraint:

- ISA900 kernels are not loadable on gfx90c, so every family must be re-derived
  natively. The tuning intel carried across is the *lever* knowledge (section 7), not
  the binaries or the per-ISA tiles.

### 6.1 Coverage-parity contract (THE rule)

> **The `tensilelibrary.dat` this pipeline produces must map EXACTLY to the
> shipped gfx900 TensileLibrary in the (shape, dtype) combinations addressed —
> no contraction, no extension.** "Addressed" cells are the canonical contract
> grid `oto.device.kernel_vocabulary.shipped_cells()`: per family, the cube shapes in
> `FAMILY_SHAPES`, family → dtype char via `FAMILY_DTYPE_CHAR` (38 cells, the
> same deck the acceptance report classifies RED/ORANGE/GREEN against).

Two clauses, both enforced CPU-only:

- **No contraction** — every shipped-addressed (family, shape, dtype) cell must
  have ≥ 1 gfx90c phase in the produced library. A shipped cell with no native
  kernel is a coverage hole that can never win its cell.
- **No extension** — no phase may address a cell the shipped library does not.
  Candidate/probe/consolidation shapes stay inside the grid; anything else must
  be justified as a deliberate footprint widening and requires an explicit
  decision, because an extended library would A/B against a floor that never
  ships it.

Enforcement (the rule has one home here; every pointer below is a mechanical
check, never a restatement):

- `python3 -m oto check library-parity` — grades `phases.yaml` + current overlays (deck +
  seed, plus a run's overlay via `--run-id`) against the grid; exit 1 on
  divergence. This is the *starter* gate for any agent or human editing the
  deck or adding candidates.
- `python3 -m oto preflight` — the library-parity verdict is one of the
  Phase-0 checks (non-fatal, like the rest of preflight).
- `python3 -m oto consolidate --commit` — refuses to install a consolidated deck whose
  cell set diverges from the grid.
- `tests/test_library_parity.py` — pins the committed `phases.yaml` + seed
  overlay to exact parity (38/38 today), so a future D1-style edit that breaks
  the grid fails CI before any GPU time is spent.

The grid's single source is `oto.device.kernel_vocabulary.shipped_cells()`; family keys,
shape lists and dtype chars live in `profiles/gfx90c.json` and are read
through `oto.device.loader.current_profile()` — never transcribed. Non-cube probe shapes (e.g. `32x4096x1`)
have no cell and are excluded from the check by construction — they are
reported separately, never counted as coverage.

---

## 7. Kernel Levers That Matter on gfx90c

Operational ordering: **coverage first**. Lever selection is subordinate to covering
every function of the 28-family footprint (section 6). The levers below are the
measured truths (frozen prior conclusions in `docs/gfx90c/gfx90c_tuning_guide.md` §14 (`archive/prior_insights.md`, untracked)
§5.1) that make coverage cheap and correct on gfx90c.

Rate card (peaks @ 1800 MHz) — canonical table lives in
`docs/gfx90c/gfx90c_theoretical_limits.md` §5 and is derived per call from
`oto.device.loader.current_profile().peak_gflops` (`oto.device.derive_limits`);
this file does not restate the numbers. The single rule that matters here:
**BF16 and INT8 are single-rate on this part (no dp4a), FP64 runs 1/16** — the
prior campaign's 3226-for-BF16/INT8 prose was hardware-wrong.

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

### 7.1 What the base already has: the pinned Tensile defaults

No winner in `cells_resolved.json` names `BufferLoad`, `PrefetchGlobalRead`,
`AggressivePerfMode`, `MaxOccupancy`, `UseSgprForGRO`, `GlobalLoadVectorWidthA/B`,
`NumLoadsCoalescedA/B`, `InnerUnroll`, `FractionalLoad`, `NonTemporalA/B`, or the
`*Read2`/`*Write2` pair. **Unset is not off**: Tensile fills every absent knob
from `defaultBenchmarkCommonParameters` (`Tensile/Common.py:1507-1670` at the
pinned commit `e8a8999e`). Read from that checkout:

| knob | default `@ e8a8999e` | consequence |
|---|---|---|
| `BufferLoad` / `BufferStore` | `True` | the buffer-load path is already active in every winner |
| `StaggerU` | `32` | swizzle is already on; `StaggerUStride 256`, `StaggerUMapping 0` |
| `MaxOccupancy` | `40` | uncapped, as AMD ships |
| `AggressivePerfMode` | `1` | |
| `PrefetchGlobalRead` / `PrefetchLocalRead` | `1` | |
| `UseSgprForGRO` | `-1` | auto/heuristic |
| `GlobalLoadVectorWidthA/B` | `-1` | resolves to `VectorWidth` |
| `AssertFree0/1ElementMultiple` | `1` | `GNP` guard fails closed at default; `=2` lifts it for the CC paired widen |
| `LocalReadVectorWidth` | `-1` | → `VectorWidth` on non-MI (`SolutionStructs:3310-3315`); no VGPR-saving rule follows (corpus3 Q-A) |
| `StoreVectorWidth` | `-1` | nominally → `VectorWidth`, but non-MI derived `gwvw` takes precedence (`Common:1192-1195`); deprioritized |
| `DirectToLdsA/B` | `False` | 4-byte guard (`GLVW × bpe == 4`) excludes CC/ZZ/DD; SS/HH-only (corpus3 Q-A) |
| `NumLoadsCoalescedA/B` | `1` | |
| `InnerUnroll` | `1` | |
| `GlobalSplitU` | `1` | |
| `FractionalLoad` | `0` | |
| `NonTemporalA/B` | `0` | |
| `LocalRead2A/B`, `GlobalRead2A/B` | `True` | wiki defaults; the `*Read2` path may be dead (see §7.2) |
| `LocalSplitU` | `1` (effective) | not in the defaults block; the real default is 1 |

**The rule this gives the deck.** "No winner sets knob X" means *never explicitly
set*, **not** *never varied*. A candidate whose value equals the default above
re-measures the baseline; only a non-default value is an experiment. This is why
`KNOB_SWEEPS`' `BufferLoad: True` row was removed on 2026-10-14 — the default is
already `True`, so the row tested nothing. `TENSILE_KNOB_DEFAULTS` in
`oto/tensile/family_decks.py` is the machine-readable copy of this table, and
`tests/test_knob_sweep.py` asserts every sweep row offers at least one non-default
value.

### 7.2 The never-exercised levers, mechanism-verified but unmeasured

From `corpus2.md` (pass 2; raw text `docs/gfx90c/gfx90c_tuning_guide.md` §15 (`archive/corpus2.pass2_20261014.md`, untracked)), which is
source-inspection of upstream Tensile, **not** a gfx90c measurement. Treat the
mechanisms as verified and any speedup as unmeasured.

- **`UseSgprForGRO`** moves global-read *offset* state from VGPR to SGPR: one VGPR
  base plus several SGPR offsets, not every address. Requires `BufferLoad=1`
  (already satisfied, §7.1) and forbids `ShiftPtr`. Trade: fewer VGPR for more
  SGPR and possibly more scalar address instructions. The historically-quoted
  "4–8 VGPR saved, 8–16 SGPR spent" is a draft claim, not a local measurement.
- **`StaggerU` is silently ignored when `BufferLoad=0`** — already encoded in
  `oto/tensile/gates/occupancy.py` `_swizzle_feasible`. Because `BufferLoad`
  defaults `True`, the deployed swizzle is live.
- **`MaxOccupancy=N` pads per-workgroup LDS to `DeviceLDS // N`** (floor), so it is
  a pure occupancy clamp. One draft had `ceil`; the inspected path is floor.
- **`AggressivePerfMode=2`'s two-waves/SIMD LDS cap is UNCONFIRMED at the pinned
  commit** (corpus3 Q-E ii). `Common.py:1310-1313` describes it, but no explicit
  mode-2 branch was found in the pinned writer/solution-validation path
  (`beAggressive` is truthy-tested). The deck's APM row still sweeps 1/2 — mode 2
  may differ via `s_setprio` — but do not call it occupancy-capped until a
  mode-1-vs-2 LDS allocation diff proves it.
- **`DirectToLdsA/B` is refused unless `GlobalLoadVectorWidth × bytesPerElement
  == 4** (`isDirectToLdsDoable`, `SolutionStructs:2358-2415`), plus whole-wave
  WGs, no `TLU==UnrollMajorLDS`, no `LocalSplitU>1`, and TLU-free needs
  `TransposeLDS=1` (itself MI-only). Consequence: **illegal for CC/ZZ/DD**
  (8/16 B elements); SS/HH-only, and it bypasses VGPR *staging* without shrinking
  the LDS tile. Not decked; gate-hardening is a post-run follow-up.
- **`ScheduleIterAlg` 2/3 are refused for non-MI Assembly** (`SolutionStructs:
  2865-2869`); 0/1 need an emitted-ISA diff before any budget. **`StoreRemapVectorWidth`
  ≠ 0 is refused without matrix instructions** (`:3861-3875`) — remove from any
  candidate list. **`ScheduleGlobalRead`/`ScheduleLocalWrite` have no direct use
  in the pinned Assembly writer** — parsed but unproven; ISA-diff preflight
  before benchmark budget. **`StorePriorityOpt` is real** (`s_setprio` in the
  store path) but an arbitration effect, not an issue-count reduction —
  low priority for issue-bound kernels. **`PersistentKernel` is not forwarded by
  this port's writer** — hold until a forwarding change lands.
- **`WorkGroupMapping=7/14 is syntactically legal** (domain is the full
  `range(-1024,1025)`) **but WGM is a J-dimension traversal block height, not a
  CU count** (`wgSerial = wg0 + (wg1 % WGM) * nwg0`). On grids shorter than 7 in
  the mapped dimension (e.g. MT128 on 256×192) it may not change traversal at
  all. Not swept; trial only where the generated mapping differs.
- **`LocalSplitU`** is `WorkGroup[2]` and splits the summation dimension *inside* a
  workgroup; it does **not** multiply the output grid (`GlobalSplitU` does). A
  TensileLite dtype guard might exclude complex, but the project's own
  `validate_config` accepts it for every family (`docs/gfx90c/gfx90c_tuning_guide.md` §13 §8.1), so
  the local gate at `e8a8999e` is the authority.
- **`GlobalLoadVectorWidth` ≠ `VectorWidth` and ≠ 1** is rejected by Tensile
  (`SolutionStructs.py:4584-4596`, "must be == VectorWidth … or == 1") **only when**
  `not bufferLoad or not GuaranteeNoPartialA`, and `GuaranteeNoPartialA` is
  `AssertFree0ElementMultiple % GLVW_A == 0` on a `TLUA` operand (`:4177-4183`;
  `bufferLoad` is true only for `KernelLanguage: Assembly`). With the default
  `AssertFree0ElementMultiple=1` that reduces to "`GLVW` is `1` or `== VectorWidth`".
  `setGlobalLoadVectorWidth`'s pv reduction (`:2010`) can also cancel an explicit
  value back to 1. The gate models all three (`oto/tensile/gates/loads.py::_glvw_for`
  + `_Operand._restriction_active`), matching the real `Ailk_Bljk` / `VW4` / `GLVWA2`
  refuses (`failurelogs.txt`; reference-rerun hashes `7f866dcf` / `a0edeb30`). So
  widening is **not** a free lever — unpaired it is a refusal or a no-op, and the one
  realizable widen is the CC-only pair `GLVW=2 + AssertFree0ElementMultiple=2`
  (`docs/gfx90c/gfx90c_tuning_guide.md` §13 §8.1, §9 D4) — swept as a trial row since 2026-10-14.
  Local writer/ISA wins over any general statement.

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

### 8.1 Reading the raw evidence (canonical, do not re-derive)

Getting these wrong produces confident, wrong conclusions. `oto.tools.run_census` encodes
all of them and drives oto's own loaders, so use it instead of hand-parsing.

- **A `2_BenchmarkData` CSV is a multi-size sweep, one row per shape** — not one
  row per measurement. Column 0 is the **row index**, not GFlops. **GFlops is the
  last column whose name looks like a kernel name.**
- **Shape is `SizeI x SizeJ x SizeL`; `SizeK` is 1.** The sweep varies the *problem
  size*, so the cube side is the L dimension, not K.
- **`MacroTile` / `ThreadTile` come back as strings** (`"128x128x16"`), and
  `ThreadTile` in particular is lowercase (`"8x8"` vs `"8X8"`). Parse, never
  assume ints or case.
- **A run directory may be gone.** Registry-only runs (e.g. `run_20260919_213727`)
  have no YAML; their records carry only a 12-key `config` snapshot. The 13 native
  winner cells that rely on it are flagged partial, not silently treated as complete.
- **Family comes from the run's own `FamilyLabel`.** Do not derive it from the live
  `phases.yaml`: the reference `hh_hpa` / `hs_hpa` phases are no longer listed there,
  so a YAML lookup silently folds them into `HH`.
- **Winner aggregation is median-per-kernel, then max** — never max over raw
  samples, or one lucky seed becomes the family's "best" config.
- **Bytes per element for the global load:** S 4, D 8, H 2, **C 8, Z 8** (complex
  types are 8 B, not 4/8), I8 1, B 2. Hard cap `GLVW x bytes <= 16`, so
  `GLVW` targets are SS 4, DD 2, **CC 2, ZZ 2**, HH 8.
- **Both arms are the same silicon** (same gfx90c APU); the "spoof" arm is the same
  device running the gfx900-tuned config deck. Identical configs do not agree
  between the two run trees (mean −5.30%, median −1.56%), so a cross-arm delta
  needs interleaved controls.
- **`unified_measurements.csv` is not an A/B input** — partial provenance and
  config fields.

### 8.2 Config legality is a 4-gate preflight, not a launch-time surprise

A config can pass divisibility, assembly-class and LDS checks and still die at
kernel-generation time. The four gates, all CPU-side and orchestrated by
`validate_config` (`oto/tensile/candidate.py`):

1. **divisibility** — `GLVW % mv/pv == 0` and `% lpv == 0`
   (`oto/tensile/gates/loads.py`; `validate_config`)
2. **assembly class** — MT/TT/DepthU/Threads/StaggerU/FP16 GSU clamp
   (`assembly_class_valid`, `oto/tensile/gates/assembly.py`)
3. **LDS + padded footprint** — per-thread LDS in VGPR-equivalent registers and
   the padded footprint, including the coupled swizzle
   StaggerU/StaggerUMapping/StaggerUStride domains (`ldspad_feasible`,
   `oto/tensile/gates/occupancy.py`)
4. **register-file occupancy** — `occupancy_feasible`
   (`oto/tensile/gates/occupancy.py`)

**Bytes per element, per dtype, from Tensile's own writer.** `DataType.numBytes()
= int(numRegisters * 4)`, so complex double (`'reg': 4`) is **16 bytes**, complex
single (`'reg': 2`) is 8, `f64` 8, `f32` 4, `f16` 2. Two consequences that are
easy to get wrong:

- **Since 2026-11-14 the LDS gate carries `BYTES_PER_ELEMENT["Z"] = 16`** —
  the Tensile Table verbatim — with `LDS_BUDGET` unchanged (16384). For ZZ the
  wall is `(MT0+MT1)*DepthU <= 1024`; the D2/D3 decision trials (64x64x16,
  128x32x8, 32x128x8) are refused by the gate by design. **See
  `docs/gfx90c/gfx90c_theoretical_limits.md` §6.1 before quoting a ZZ LDS byte count.**
- §8.1's "complex types are 8 B" refers to the **global-load** element width
  under the `GLVW x bytes <= 16` cap — a different quantity on a different path.
  Both can be true at once; they are not a contradiction.

Gate 4 is the one that was silently absent. Tensile sets
`overflowedResources = 4` ("Occupancy limit", user-visible as
`Generating kernel source resulted in error 4`) when the register file cannot
hold one workgroup. Run `python3 -m oto check candidates` to sweep a deck; it exits
1 on any illegal config, so legality is provable **before** a GPU run. That error
is now *caught*: it is the workgroup register-file rule modelled below
(`occupancy_feasible`), so a phase that carries it is refused at preflight rather
than dying on the GPU — see `claude.md` §2.2 / §5 and `docs/gfx90c/gfx90c_tuning_guide.md` §13
§R24. Gate semantics live in `oto/tensile/gates/*` (each gate module documents
itself).

**The occupancy rule (corrected — two constraints, not one).** The full
current reading lives in `docs/gfx90c/gfx90c_tuning_guide.md` §6 (this file carries
the mechanism, the measurement trail and the Z-quantisation consequences; the
harness metrics gates in `oto/tensile/gates/*` are normative). The *per-thread*
constraint is on **ThreadTile**: a thread holds `TT0 x TT1` accumulators, each
`weight` VGPRs, so `accVGPRs = TT0*TT1*weight` is checked against
`ACCVGPR_BUDGET = 128` (the 256-VGPR/thread ISA cap with headroom). Measured on
gfx90c complex (Z, weight 8) with Tensile's own writer: `TT 2x2` → 63 VGPRs ok,
`TT 4x4` → 154 ok, `TT 8x4` → 271 FAIL, `TT 8x8` → 519 FAIL; the pass/fail
boundary is exactly `accVGPR > 128`. An earlier model used
`R * MacroTile_area <= 65536/2` (a "2× headroom" rule) and was structurally
wrong in both directions — it passed the 8 ZZ `TT8x4` phases that then died 116
times each in `run_20260928_024945` — and it is retired.

The **second, independent** constraint is the *workgroup register file*: Tensile
needs `65536 // NumThreads // max(vgpr, agpr) >= 1`, and since the accumulators
are always allocated (a sound lower bound on `vgprPool.size()`), the rule is
`weight * MT0 * MT1 * LocalSplitU >= 65536` → error 4. Here **MacroTile IS in the
expression** (ThreadTile cancels out), so it caps tile *area* at `65536/weight`:
CC `128x64`, ZZ `64x64`/`128x32`. The old area model was reaching for this rule
with the wrong threshold (32768, not 65536) and the wrong boundary (`>`, not
`>=`). A *third* cap applies when `LocalSplitU > 1`: the LDS reduction buffer
`LSU*MT0*MT1*computeBytes <= 65536`. All four limits (with the LDS tile proxy and
the classic-load divisibility rule) are listed in `claude.md` §5, are calibrated
zero-false-rejection against the corpus (2026-10-18), and must never be relaxed
to admit a candidate.

Model and calibration table: `oto/tensile/gates/vgpr_model.py` (`ACCVGPR_BUDGET`,
`MAX_LDS_BYTES`, `MEASURED_VGPR`, `measured_accvgpr`); decisions:
`occupancy_feasible`. The gate can kill a family through thread-tile width *or*
through MacroTile area — the two are different rules and neither is redundant.

---

### 8.3 Clock and thermal protocol for this box

The device's clock is not stable and is **not** pinned by default: idle drops to
400 MHz, and boost only arrives once the part is warm (measured corpus medians
~930 MHz at 46–48 °C rising to 1800 MHz at 76–78 °C). So a cold run measures a
different machine than a warm one, and two arms measured at different
temperatures are not comparable. The floor arm has no telemetry at all, so no
cross-arm clock correction is possible. (The sole LOSS in
`run_20261013_214649` was first read as this failure, but it was a candidate
sweep-order defect — `docs/gfx90c/gfx90c_results.md` §13.4 — and the clean re-run reads CC:256 as
TIE.)

Steps, all operator-side (TTY):

1. **Pin the clock** so the level is a chosen number, not a policy outcome:
   `echo manual > /sys/class/drm/card0/device/power_dpm_force_performance_level`
   then `echo 7 > /sys/class/drm/card0/device/pp_dpm_sclk` (highest level).
2. **Warm up to thermal equilibrium** — 25% of the iterations before the
   measured window. Realistic data, not zeros: all-zero or low-toggle inputs
   can inflate clocks by >50%.
3. **Flush L2 between repeats** for memory-bound shapes, so a hit is not
   measured as a miss.
4. **Batch short kernels** (150 µs–80 ms) to amortise dispatch overhead.
5. **Log per phase**: median clock, temperature, and run order, and interleave a
   fixed reference kernel every N runs to detect drift.
6. **Acceptance gate**: coefficient of variation < 1.5% before a delta is
   believed.
7. **Randomize within blocks** (block by dtype/shape; ref-kernel at block
   boundaries). Report median **and** MAD/spread with raw repeats kept; re-run
   a block whose reference drifts (corpus3 Q-F).
8. **Flush rule**: `flush_count >= 1 + cache_size / problem_footprint`
   (`Common.py:88-110`); below-1-MB footprints get separate cold/warm-L2
   variants instead of one mixed number.
9. **Record schema** (per phase): timestamp, phase, problem_id, dtype, shape,
   config_id, randomized_position, reference_flag, cache_mode, repeats,
   raw_times_us, median_us, MAD_us, sclk_source, spoof_clock_sclk_hz,
   spoof_clock_coverage, observed_sclk min/median/max, temperature min/median/max,
   power level, LDS_bytes, VGPR/thread, SGPR/thread, scratch_spill_bytes,
   code_object_id. Telemetry-incomplete floor-arm rows are tagged, never
   clock-corrected.

Without step 1 and step 6 the run cannot distinguish a kernel improvement from a
thermal or DVFS difference, which is the single largest confound in this corpus.

**External corroboration (CUTLASS measurement guidelines, [Transfer only]).** The
literature agrees on the shape of this protocol — separate warmup and profiling
loops, minimal gaps between launches, controlled caches, stable clocks, and enough
samples to average out timer overhead — and is equally clear that its own numbers
are NVIDIA-specific, not gfx90c constants (it reports ~3 s of clock settling in its
environment and >1,000 profiling iterations for a large GEMM). **No universal
iteration count and no universal ±% tie band exist**; this project's bands (§8
±5 % parity; the guide's tighter M1 band) are its own predeclared policy, not an
external standard. The one transferable rule: distinguish a first-run clock
transition from a wave tail, and retain raw samples rather than only a best time
([CUTLASS methodology](https://docs.nvidia.com/cutlass/latest/media/docs/cpp/gemm_performance_measurement_methodology_guidelines.html)).

**AMD-specific methodology (still no GCN5 constant).** AMD's own guidance is closer
in kind than CUTLASS but is still not a gfx90c constant: Tensile's defaults are
`NumWarmups=0`, `NumBenchmarks=1`, `SleepPercent=300`, `PinClocks=False` — defaults,
not proof of statistical adequacy; AMD's MI300 max-FLOPS example runs each GEMM
~1 s with ~25 % warmup / 75 % measurement; and AMD Primbench reduces noise with
adaptive timed batches, a coefficient-of-variation threshold, a minimum runtime,
initial warmup and clock/temperature awareness. Adopt the *procedure* — warm to
stable clocks, batch long enough to amortise the timer, randomise candidate order,
repeat independent rounds, keep raw samples and spread — never a copied count
([Tensile Common.py](https://github.com/ROCm/rocm-libraries/blob/develop/shared/tensile/Tensile/Common.py),
[AMD max-FLOPS](https://rocm.blogs.amd.com/software-tools-optimization/measuring-max-achievable-flops-part2/README.html),
[Primbench](https://rocm.docs.amd.com/projects/primbench/en/latest/conceptual/primbench-noise-reduction.html)).

### 8.4 Do not cite — unverified claims that circulate in this project

Claims that have been searched for and **not** confirmed. Citing them is a
defect, not a shortcut. Each names what was actually found, if anything.

| Claim | Status |
|---|---|
| "Tile: A Faster Tiling Approach for AMD GPUs" (ASPLOS'20) | Not located in ACM/IEEE libraries. Do not cite. |
| "MI250-optimal config on A100 drops to ~7% of A100-optimal" | The 7% figure is not in arXiv:2505.03780, which reports ≥20% up to an order of magnitude for Triton flash-attention. Cite the paper's own number. |
| "142k CLBlast tuples, 5 GPUs, dynamic range 1.8×–13.2×" (arXiv:2507.15277) | The parameterised stats are unverified from the abstract. Cite the paper only for its qualitative portability thesis. |
| "ISC 2026 CUTLASS FP8, 1.00 waves/SM, 14% achieved occupancy" | Datapoint not located in accessible proceedings. |
| "PERKS (SC'23) gives 1.15×–1.4× on gfx90c" | PERKS is dGPU/NVIDIA; there is no gfx90c APU data. |
| "gfx1151 `auto` DPM pinned at 1100 MHz; `profile_peak` gave +37.8%" | No primary source verified for gfx90c. Treat as illustrative of the mechanism only. |
| COSTA / FASTEST / BASS / BEST / Pyramid / MagicLine / SeerNN / PlanGen / GemmLab / Charo analytical GEMM / Fugerite et al. | Bibliographic ghosts in this corpus — none verified to exist as cited. |
| A universal "2 waves/SIMD is the right target" rule | Not a law; varies with ILP versus memory latency. |
| "`AggressivePerfMode=2` caps LDS to 2 waves/SIMD on this commit" | Comment says so (`Common.py:1310-1313`); no explicit mode-2 branch found in the pinned writer/validation. Unconfirmed until a mode-1-vs-2 LDS diff proves it (corpus3 Q-E ii). |
| "`LocalReadVectorWidth=2` saves VGPRs in CC/ZZ" | Default resolves to `VectorWidth` non-MI; accumulators are unaffected by read width. Judge from emitted VGPR/issue deltas, not the option value. |
| "DirectToLDS helps CC/ZZ/DD" | Pinned `isDirectToLdsDoable` requires a 4-byte global load; their 8/16 B elements fail it. SS/HH-only. |
| "WGM=7 is the natural optimum for 7 CUs" | WGM is a J-dimension traversal block height (`wgSerial = wg0 + (wg1 % WGM) * nwg0`), not a CU count. No verified 7-CU raster rule exists. |
| "`ScheduleGlobalRead`/`ScheduleLocalWrite` tune the non-MI kernel" | No direct use in the pinned Assembly writer. ISA-diff preflight required. |
| "Vega has a packed/dual-lane FP32 FMA (`V_PK_FMA_F32`)" | Vega ISA lists `V_PK_FMA_F16` (packed half) and `V_MAD_MIX_F32` (mixed-width) but **not** `V_PK_FMA_F32`; `V_MAD_MIX_F32` is not two packed FP32 FMAs. No FP32 lane-doubling exists on this part. |

Full detail, including what each source *does* say, is in `docs/research/kernel_tuning.md`
§9 — same list, kept in one place, with a per-row "what is actually known" and one
entry resolved (AMD's shipped library is **not** uniformly small-tiled). The
pass-1 sweep's own record of the same list is `docs/gfx90c/gfx90c_tuning_guide.md` §15 (`archive/corpus.pass1_20261014.md`, untracked)
§4; cite §9, not the archive.

## 9. Reporting Toolchain

Pipeline (in order):

1. `python3 -m oto tune` (the driver) + `oto/ledger/registry.py` — persist raw benchmark records to SQLite
   (`gfx90c_results/registry.db`, append-only `records`).
2. `oto/metrics/benchmark_analytics.py` — per-cell analytics, native-vs-spoof deltas, cell-status classification (RED = missing contract cell, ORANGE = <50% ceiling, GREEN = at/above).
3. `oto/metrics/acceptance_report.py` — builds the `gfx90c_results/acceptance_report.json` + `.html`
   (single-file dashboard). Report dtype extraction is token-based
   (`extract_dtype_from_phase_id`), no longer regex-dependent.
4. `run_status.py` — progress/ETA accounting, and the live TTY panel
   (`LiveStatus`) that `oto tune --live` paints while phases execute.

### 9.1 Execution time in the acceptance report

`execution_timing` in the report JSON/HTML is three distinct numbers, never
collapsed into one "runtime":

| field | meaning |
|---|---|
| `native_run.elapsed_minutes` | wall clock of the run being reported — one pass of the deck |
| `reference_chain.elapsed_minutes` | wall clock summed over the gfx900 chain |
| `phase_busy.minutes` | sum of per-phase `started`→`ended` spans |

The first two are separate because the floor is usually a *resumed chain*: the
head run's cost is a fraction of the floor's total, so one combined figure
would understate the floor by however many resumes it took. `phase_busy` is
below wall clock by config generation, Tensile build and queueing; a large gap
means an ETA is timing harness overhead, not the GPU.

A run that is still in flight has no execution time yet. It reports
`elapsed_minutes: null` and `in_flight: true` rather than `0.0`, so
"not finished yet" is never read as "instant".

This is the module docstring of `oto/metrics/report_models.py`
(`AcceptanceReport`).

### 9.2 Live TTY status

`run_status.LiveStatus` repaints a compact panel (state, decided/total, progress
bar, elapsed, ETA, tally) into the terminal while a run executes:

- A **background thread** repaints, because the main loop is blocked inside
  `execute_phase` for minutes at a time — a caller-driven pump would freeze.
- **stdout is wrapped** in `_PanelStdout`, which erases the panel before any
  other write. Without it, the run's own `Skipping phase ...` lines land under
  the panel and the next repaint shreds them.
- A **non-TTY** (piped log, CI) gets appended plain lines, never ANSI, so logs
  stay readable.
- The panel **catches `BaseException`**: `build_report` raises `SystemExit` when
  the registry does not exist, which is exactly the state a first run starts
  in, and `SystemExit` is not an `Exception`. A status display must never be
  the reason a run dies.

Flags: `--live on|off` (default on), `--live-interval SECONDS` (default 15).
`oto status --watch` remains the standalone full-panel view.

This is the module docstring of `oto/metrics/render_status.py`.

Acceptance ceilings: per-family bars come from `docs/gfx90c/gfx90c_theoretical_limits.md`
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
- Prior-campaign jsonl artifacts (`experiment_db.jsonl` / `benchmark_registry.jsonl`),
  if present in an archive, remain **in place** — never rewritten, never deleted,
  never "migrated in place". Readers may ingest them into SQLite as **new** `records`
  rows (copy-forward), never truncate the jsonl. The canonical **live** ledger is
  `gfx90c_results/registry.db`; no jsonl ledger currently exists there.
- `docs/gfx90c/gfx90c_results.md` — its `<!-- DERIVED:* -->` blocks *and* its hand prose.
- `acceptance_report.json` + `acceptance_report.html` (in `gfx90c_results/`) — regenerated from data, never hand-repaired.
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
  new attempts, and must not become the `oto tune` feed target. Harvest still
  **appends rows to `phases.yaml`**.
- **A changed fingerprint is a NEW attempt.** Old attempt + data stay untouched.
- Retirement **appends** a `retire` record (or equivalent `record_type`) that
  marks exclusion from scoring — it never removes rows, and a retired record is
  always reversible by a later append.
- Phase-number reservations and run-order are asserted (order self-check) so a
  run can never silently skip or reorder intended work.
- Stats/analytics pipeline (`oto/metrics/benchmark_analytics.py` → `oto/metrics/acceptance_report.py`) reads derived data from the
  SQLite `records` table (via the registry). The driver may **also** append a jsonl
  *export* of new `records` (dual-write). Dual-write is export, not a second
  source of truth. Canonical ledger = `records`.

### 10.3 Derived artifacts

- `oto/metrics/acceptance_report.py` `write_report()` writes `acceptance_report.json` and its `.html`
  dashboard wholesale from the registry data.
- Legacy `make_results_md.py`-style `docs/gfx90c/gfx90c_results.md` `<!-- DERIVED:* -->` marker-block
  regeneration no longer exists; `docs/gfx90c/gfx90c_results.md` hand prose is append-only.
- The single peak authority is `oto.device.loader.current_profile().peak_gflops` (see section 7); derived
  prose that contradicts it is regenerated, not hand-patched.

### 10.4 Consequences of a change

- New measurement → **append** new records and a new run directory; re-render DERIVED
  blocks by regenerating, never by hand-tuning numbers.
- Methodology or math change → revalidate derived conclusions; the derived output may
  change, but the underlying data rows do not.

---

## 11. Glossary

- **run** — one execution of the driver over a set of phases (`python3 -m oto tune`
  or `python3 -m oto bench` with semantic filters `--targets`/`--family`/`--pattern`/`--shape`
  and stages via `oto run --stage`, or `python3 -m oto bench --refresh` for the spoof floor);
  captured in an era-named
  `run_YYYYMMDD_HHMMSS/` directory.
- **phase** — one manifest row of the driver (`phases.yaml`); the spoof/reference
  floor lives in its own `gfx900_ref_*` run chain (recalled via `--resume`, never
  re-rolled), and phase-number gaps are reserved (see `docs/changelog.md`).
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
- **RED cell** — a contract cell with no candidate measurement at all (MISSING);
  ORANGE = measured but below the 50% realistic-ceiling gate; GREEN = at/above. Distinct
  from the retirement list (stable cells excluded from re-benchmarking).
- **EnqueuesPerSync / Syncs** — brick sizes; small for smoke gates, large for
  production benchmarking (smoke-vs-production note, section 4).
- **tensilelibrary** — the assembled library artifact (`.dat` / `.co`) plus dispatch
  metadata that Tensile/rocBLAS select from.

---

Related documents: `docs/changelog.md` (the evolution narrative), `docs/gfx90c/gfx90c_theoretical_limits.md`
(ceiling authority), `docs/developer/invariants.md` (footprint contract), `docs/gfx90c/gfx90c_tuning_guide.md` §14 (`archive/prior_insights.md`, untracked)
/ `docs/gfx90c/gfx90c_tuning_guide.md` §14 (`archive/prior_research_archive.md`, untracked) (frozen prior conclusions).