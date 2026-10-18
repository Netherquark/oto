# gfx90c Kernel-Tuning Guide — the cookbook (caveman, full)

> Plain words. Hard numbers. Every claim traceable in the repo (cite keys below).
> This file formalizes the kernel-tuning research: what the deck controls, what
> actually wins, why "nothing moved", and what to try next. Read
> `gfx90c_theoretical_limits.md` first — its §5 ceilings are the acceptance bar.
> Cite keys: **L**=gfx90c_theoretical_limits.md, **P**=potential_configs.md,
> **K**=kernel_db.json (`oto/harness/kernel_db.py`), **O**=oto/device/peaks.py,
> **D**=implementation_plan.md, **M**=oto/harness/measure_vgprs.py,
> **C**=oto/harness/cell_knob_diff.py. Numbers below are kernel_db post-2026-10-09
> rebuild (all runs folded), typecode-filtered, median-of-seeds per cell.
> §11 is the loop for proposing the next candidate.
> §1.1/§1.2 are the primary-source knob reference — Tensile's own legal domains
> and the 7-CU geometry behind every tile choice; §9.1 is the virgin-axis census.
> Before changing a domain in `oto/tensile/synthesis/db_knobs.py`, read §1.1 and
> then prove the change with `python3 -m oto.tools.deck_review legality`.

## 0. The one-line truth

The deck controls **geometry and residency**, not the pipe. Large squares are
already pinned to the ALU wall (M1). The real headroom is the **small cells**
(M2: the machine idles below 25 % residency) and the **complex cells**
(M3: shortfall is memory/occupancy — pads/GSU/PGR axes, reopened 2026-10-09). Everything else is
measurement hygiene (M4: suppressed clock), not tuning.

## 1. Knob surface — what the deck actually controls

The knob → Tensile forwarding map (which key `_write_phase_config` emits
verbatim, and which CPU gate governs it) is a fact about the writer and lives in
the module docstring of `oto/tensile/config_writer.py`. For the *tuning* read —
which knob actually matters and in which regime — see §4 and §5 below. The
table itself, restated so this file stands alone:

| knob | what it does | legality gate | forwarded by `_write_phase_config` |
|---|---|---|---|
| MacroTile | tile dims M×N (+DepthU in the string) | occupancy (LDS) + assembly | yes |
| ThreadTile | accumulators per thread = TT0·TT1·weight VGPRs | occupancy (VGPR) | yes |
| VectorWidth / GLVW | global-load width; **16-B hardware cap** | divisibility | yes |
| DepthU | K-depth of the LDS tile | LDS budget | yes |
| GlobalSplitU | waves over K (the M2 lever) | assembly (complex/no-MFMA) | yes |
| WorkGroupMapping | CU–tile mapping | — | yes |
| contraction pattern | Ailk_Bjlk (NT) vs Alik_Bljk (TT) etc. | — | yes |
| **LdsPadA/B** | bank-conflict pad per LDS row (M3 lever) | **`ldspad_feasible`** | **yes (Group C)** |
| **StaggerU / StaggerUMapping / StaggerUStride** | store stagger; forwarded as a **coupled trio** | **`ldspad_feasible`** | **yes (Group C)** |
| **AssertFree0ElementMultiple (AF0EM)** | half-Assembly GSU>1 legality | **`ldspad_feasible`** (+ class rule in `assembly`) | **yes (Group C)** |
| **StoreCInUnroll** | C-store unrolling | **`ldspad_feasible`** | **yes (Group C)** |

The exact forwarded set is `FORWARDED_GROUP_C_KNOBS` in
`oto/tensile/config_writer.py`:
`("LdsPadA", "LdsPadB", "AssertFree0ElementMultiple", "StaggerU",
"StaggerUMapping", "StaggerUStride", "StoreCInUnroll")`.

Group C (2026-10-09): the pad/RCT knobs were silently stripped by the writer —
candidates carrying them benchmarked WITHOUT the knob (167/167 reference kernels
ship pads). They are now forwarded verbatim behind `ldspad_feasible`
(`oto/tensile/gates/occupancy.py`), which checks the padded-LDS footprint
against the 16 384-B/WG budget, the coupled StaggerU/StaggerUMapping/
StaggerUStride domains, `StaggerUStride >= DepthU·bytesPerElement` when
`StaggerU>0`, and `AF0EM >= 1` (the `AF0EM>=2` half-Assembly GSU rule itself is
`assembly.assembly_class_valid`). The backwards `StaggerUStride` gate — it
refused exactly the legal swizzle values, which is why swizzle forwarding looked
"blocked" — was fixed 2026-10-09. The generator no longer strips the trio; tests
lock the writer, the gate and the generator.

### 1.1 Primary-source legal domains (Tensile's own `validParameters`)

The domains in `oto/tensile/synthesis/db_knobs.py` are a *narrowing* of Tensile's
legal set, so the legal set has to be written down somewhere or every domain
change is guesswork. This is it — read from `Tensile/Common.py`'s
`validParameters` (`ROCm/Tensile@develop`). **Line numbers deliberately omitted**;
the symbol names are the citation.

| knob | Tensile-legal values | what we sample | narrowing rationale |
|---|---|---|---|
| `StaggerU` | `[0,2,4,8,16,32,64]` | `0,8,16,32` | even clicks only; the odd ones are noise |
| `StaggerUStride` | `[0,16,32,64,128,256,512,1024,2048]` | `0,64,128,256` | Tensile **silently raises SUS to a whole multiple of `DepthU*bpe`**, so a draw of 256 collapses to 64 at DU16/bpe4 — most of a coarse domain is one point (P §0 R6) |
| `StaggerUMapping` | `[0,1,2,3,4]` | `0,1,2` | 3/4 are debug/special |
| `GlobalSplitU` | `1…4096` | `1,2,4` on SS/DD; **`1` only** on CC/ZZ/HH/HH_HPA/HS_HPA | **family-restricted, and the two restrictions are not the same.** Tensile allows `>1` only for single, 8-bit float, double+BufferStore, Assembly-with-half-accumulate, `_GlobalAccumulation`, or MFMA; gfx90c has no MFMA. *Structural*: complex (`CC`/`ZZ`) and half-with-f32-accumulate (`HH_HPA`/`HS_HPA`) can never run it. *Deck state*: `HH` is hardware-legal but banned by decision, because `>1` on half Assembly also needs `AssertFree0ElementMultiple>=2` and the HH deck ships `AF0EM=1` — lift it the day an HH candidate carries `AF0EM>=2`. Single home: `db_knobs.FAMILY_KNOB_DOMAINS`, read via `forward_domain` |
| `PrefetchGlobalRead` | `[0,1,2]` | `0,1` | `2` needs 2× LDS + buffering VGPRs; not admitted by the 16 384-B/WG budget on 64 KiB LDS |
| `PrefetchLocalRead` | `0…128` | `0,1` | 0/1 is the measured split |
| `1LDSBuffer` | `[-1,0,1]` | **not sampled** | halves LDS but needs `ScheduleInnerAccuracy` 2 or 3 — the strongest virgin occupancy lever (§9.1) |
| `FractionalLoad` | `[0,1,2]` | **not sampled** | `2` frees the `DepthU` choice on ragged M/N/K |
| `NumLoadsCoalesced{A,B}` | `-1…64` | `1,2,3` (`NLCA/B`) | `-1` = *least* coalescing (largest number of reads along the coalesced dim) — a distinct regime, not a synonym for `3` |
| `GlobalLoadVectorWidth{A,B}` | `[-1,1,2,3,4,6,8,16]` | **dtype-dependent** | the verified 16-B cap (`L` §1) makes `GLVW*bpe ≤ 16`; worst legal per dtype is S 4, H 8, D 2, C 2, **Z 1**. A flat `(1,2,4)` domain is a guaranteed-refusal generator for DD/CC/ZZ — see `FAMILY_KNOB_DOMAINS` |
| `LocalReadVectorWidth` | `[-1,1,2,4,8,16]` | tied to `VectorWidth` | — |
| `VectorWidth` | `[-1,1,2,3,4,6,8,16]` | per-family | same 16-B cap |
| `LdsPad{A,B}` | `-1…127` | `0,1,2,4` | `-1` means "same as VectorWidth if TLU=0 else 0" — derivable, not worth a draw; `1` is reported as the value the floor never uses (§9.1, `check`) |
| `LdsBlockSizePerPad{A,B}` | `[-1,0,64,128,256,512,1024,2048,4096]` | **not sampled** | per-block padding *without* redesigning the tile; must be ≥ `unrollDepth*bpe`. Virgin (§9.1) |
| `TransposeLDS` | `[-1,1,0]` | **not sampled** | TLU=0 matrices only; aligns LDS layout with VALU reads in the absence of MFMA |
| `UnrollMajorLDS{A,B}` | `[False,True]` | **not sampled** | "beneficial for smaller data types"; relieves `VgprForLocalReadPacking` |
| `WaveSeparateGlobalRead{A,B}` | `[0,1]` | **not sampled** | splits LDS by wave → fewer cross-wave bank collisions (§9.1) |
| `ThreadSeparateGlobalRead{A,B}` | `[0,1,2,4]` | **not sampled** | `2` is documented to pair with `WaveSeparateGlobalRead` |
| `NonTemporal{A,B,C,D}` | `0…7` | **not sampled** | 1=`glc`, 2=`slc`, 3=both; cache-hint bits matter on a 1 MiB L2 |
| `WorkGroupMapping` | `-1024…1024` | `1,2,3,4,-1,-4` | **8 is the floor's dominant value only because it was tuned for 56–60 CUs**; on 7 CUs it asks for 8 workgroups in the J-column before wrapping. Negatives swap wg0/wg1 — geometrically neutral on square tiles, and the negative family has *never* been generated |
| `MaxOccupancy` | `1…40` | **not sampled** | cap LDS to buy occupancy |
| `InnerUnroll` | `[1,2,4,8,16,32,64]` | per-tile | — |
| `DepthU` | `-16…-1` ∪ `2…1024` | `4,8,16,32` | negatives are the "derived" sentinel |
| `DepthULdsDivisor` | `[1,2,4]` | **not sampled** | needs `ScheduleInnerAccuracy=3` + `TransposeLDS` + `PrefetchGlobalRead≠2` + `DirectToLds=0`; cuts LDS 2×/4× |
| `StoreCInUnroll` | `[False,True]` | forwarded | C-store unrolling (Group C) |
| `StoreCInUnrollInterval` | `1…15` | **not sampled** | — |
| `PersistentKernel` | `-1…511` | **not sampled** | amortises tile assignment on a 4-tile grid (M2's real enemy) |
| `StreamK` | `[0,1,2,3]` | **not sampled** | — |
| `AssertFree0/1ElementMultiple` | `[1,2,4,8,16]` | `1,2` (rows), `4` (CC:256 batch) | **assertions, not hints.** AF0 asserts **M** (Tensile's FreeIndex[0]="I"), AF1 asserts **N** (FreeIndex[1]="J"). Recommended 16/I8, 8/half, **4/single**, 2/double. Tensile does **not** enforce the divisibility — its own comment says the generator "will assume that the ... size is some multiple", so a wrong value drops the needed predication and returns silently wrong numbers. Checked in `candidate_pool._offer_row`, the only place config and shape are both in scope |
| `AssertSummationElementMultiple` | `[1,2,4,…,1024]` | **not sampled** | asserts **K**, and Tensile applies `ASEM//GSU`, so it must also divide by `GlobalSplitU`. Same unenforced-divisibility hazard; guarded by the same check |

Tile enumeration (same source): `numThreads ∈ {32,64,…,1024}` — **workgroup size
is always a multiple of 32**; `ThreadTile` sides ≤16 or multiples of 4;
`MacroTile` sides ∈ {1,2,4,8,16,32,64,128,256,512,1024} ∪ {6,12,24,48,96,192,384,768}.
The `MatrixInstruction` shapes enumerated in the same table are **gfx908+ only and
unreachable here** (`HasMFMA=False`) — recorded as a dead end, not an omission.

**Two register bounds, not one** (both gated since 2026-10-18, 0 false
rejections; mechanics in `kernel_tuning_research.md` §4):

| bound | rule | binds on |
|---|---|---|
| per-thread accumulator | `TT0*TT1*R <= 128` | ThreadTile width |
| workgroup register file (Tensile error 4) | `R * MT0 * MT1 * LocalSplitU < 65536` | **MacroTile area** |

`R` is the accumulator VGPR weight (`S/H` 1, `D` 2, `C` 4, `Z` 8). The second
rule is Tensile's own `65536 // NumThreads // max(vgpr, agpr) >= 1`; ThreadTile
cancels out of it, so it caps MacroTile *area* at `65536/R` — `SS/HH` 65536,
`DD` 32768, `CC` 16384, `ZZ` 8192. Consequently the widest *legal* MacroTile is
CC `128x64`, ZZ `64x64`/`128x32`; the wider "headroom" tiles in
`potential_configs.md` §8.2 fill the file (65536) and are unbuildable. A third
rule bounds `LocalSplitU > 1`: the LDS reduction buffer
`LSU*MT0*MT1*computeBytes` must stay ≤ 65536
(`kernel_tuning_research.md` §4, rule 2).

### 1.2 The small-box geometry, which drives `WorkGroupMapping` and tile choice

Only **7 CUs**. Grid = `⌈M/MT0⌉ × ⌈N/MT1⌉` workgroups. Occupancy ≥2 WG/CU needs
≥14 resident tiles; ≥8 WG/CU needs ≥56. So:

| MT | tiles @256³ | tiles @512³ | tiles @1024³ |
|---|---|---|---|
| 32×32 | 64 (9.1/CU) | 256 | 1024 |
| 64×64 | 16 (2.3/CU) | 64 (9.1/CU) | 256 |
| 128×128 | 4 — **6 of 7 CUs idle** | 16 (2.3/CU) | 64 (9.1/CU) |
| 256×128 | 2 | 8 | 32 |

This is the mechanism behind M2 (guide §5): `128×128` at 256³/512³ is not a
tuning miss, it is a geometry that cannot fill the machine. Payoff ranking for
the tile axis is therefore **H at 256³/512³, M at 1024³, L at 2048³+**.

## 2. Hardware plate book (no re-derivation — see L §1/§2)

- gfx90c = ISA (9,0,12), **7 CU → 28 SIMDs → 280 wave slots**, Wave64, 448 FP32 lanes.
- Per-thread VGPR cap **256**; 16-B global-load cap (`Z` must be VW1).
- LDS 64 KB/CU; the model budgets **16 384 B/WG** (prefetch double-buffer, §5).
- 1 MB L2; 42 GB/s realistic DDR roofline (DRAM physics 51.2). All deck squares
  ≥ ~256³ are ALU-bound — DDR is not the large-square story.

Per-family ceilings @1800 MHz / realistic bar (L §2/§5, the acceptance source):

| family | theoretical | realistic (accept ≥) | measured best |
|---|---|---|---|
| SS | 1613 | **1118.7** (69 %) | 1135.1 @1024 (native), 1123.0 @4096 |
| DD | 101 | **98.6** (95 %) | 97.0 @2048 |
| HH | 3226 | **2461** (72 %) | 2664.9 @4096 |
| HH_HPA / HS_HPA | 1613 | **1118.7** | 1441 @1024 (above the derived bar — f16 input halves traffic) |
| CC | 1613 | **1118.7** derived | 318.0 @512 (4-real-MAC floor; gap under investigation — P §2, REOPENED) |
| ZZ | 101 | **98.6** derived | 24.0 @1024 (same) |

CC/ZZ are **not** "permanently orange by construction". The four-`v_mac_f32`
per-complex-MAC ALU cost is irreducible (`KernelWriterAssembly.py:14975-14978`),
so the shortfall is memory/occupancy; the gfx900 complex corpus (64 CC + 26 ZZ
ships) never sampled pads, GSU>1 or PGR≠1, so those axes are the resolution
path (P §2, the ceiling caveat, reopened 2026-10-09).

## 3. Typecode = ground truth (attribution rule)

Kernel names, not phase-id text, decide the cell. The `phase_auto_*` pool used
to resolve family `'auto'` → dtype `'S'` and dumped HH/CC/DD kernels into the SS
cells (P §3: S 1024 reported **2142.55**, honest **1135.1**). Rule, enforced
everywhere (analytics, kernel_db, port_tensile):

- typecode → family: **SB→SS, DB→DD, HB→HH, CB→CC, ZB→ZZ**; layout-suffixed
  codes (HHS_BH, HSS, ZB_GB) strip the layout token first.
- **HHS/HSS are fp16-family — they count toward HH, NEVER toward SS.**
- typecode beats a contradicting phase family stamp (`[contamination]` warning,
  typecode wins); HPA/HS_HPA stamps survive (`family=HH_HPA` preserved).
- Single-letter legacy tokens (S/Z) fall back to ss/zz.

Post-fix audit (2026-10-09, kernel_db rebuilt): **0 rows** where the stored
family disagrees with the kernel typecode; **0 HH-ish kernels** in any SS cell;
the old `phase_auto_1_hh` rows are gone from SS:1024. Unit tests:
`tests/test_cell_attribution.py` (28).

## 4. What actually wins per family (measured kernel-type patterns, P §6)

| lever | winner | evidence (all-run kernel_db sweep) |
|---|---|---|
| direction | `Ailk_Bjlk` (**NT**) dominates | the only non-NT winners: DD:192 `Alik_Bljk` (TT), the DD/Z:1024 `64x32` TN pocket; the spoof is NT-everywhere too |
| MacroTile | ∝ 1/element-size: S/H 128 (96 at 256), C/D 64 (32 at 192/256), Z 32 (64x32 at 1024) | one tile serves each family's whole range |
| VectorWidth | pinned to the 16-B cap: S vw4, H vw8, C vw2, D vw1-2, Z vw1, HPA vw4 | not free; the cap is hardware |
| DepthU | 8 for S/D/C/Z, 16 for H/HPA | family-locked, not a sweep knob |
| WorkGroupMapping | 4 everywhere; **8 is a real CC lever** | CC:512 WGM8 > WGM4 within-run |
| GlobalSplitU | 1 in all winners so far | the single untested wave-fill axis (Group A) |
| register hygiene | real families saturate; complex cap at the throughput wall (under investigation) | M1/M3 |

## 5. Why "nothing moved": the four mechanisms

**M1 — ceiling saturation (ties that are walls).** SS 768+ ≈ 1046–1135 vs bar
1118.7 (93–102 %); HH 1024+ ≈ 2368–2665 vs 2461; DD 768+ ≈ 89–97 vs 98.6. Both
arms sit on the SAME wall within ±5 %: SS:768 −0.5 %, SS:1365 −2.9 % (pre-fold
signs; rebuilt db now shows SS:1000 −2.9 % / SS:1024 −3.1 %, tie band). **No
config mutation moves these.** The user's "bunch of ties" is mostly this.

**M2 — wave quantization on the small cells.** 192/256 cubes with sensible tiles
physically cannot produce ≥ 40 waves:

| cell | winner (tt) | waves | waves/SIMD | ~residency |
|---|---|---|---|---|
| SS:256 | 96x96/6x6 | 36 | 1.29 | 13 % |
| SS:512 | 128x128/8x8 | 64 | 2.29 | 23 % |
| HH:256 | 32x64/4x4 | 64 | 2.29 | 23 % |
| CC:256 | 64x64/4x4 | 64 | 2.29 | 23 % |
| DD:192 | 32x32/4x4 | 36 | 1.29 | 13 % |
| ZZ:128 | 32x32/2x2 | 64 | 2.29 | 23 % |

SS:256 makes 412/1613 while SS:1024 makes 1135/1613 at ~91 % residency — **the
gap IS the residency gap.** The lever: smaller tiles keeping ≥4 waves/thread in
flight, or GlobalSplitU to turn waves over K (Group A).

**M3 — the Tensile complex throughput wall (CC/ZZ).** CC caps ≈290–318 and ZZ
≈21–24; the gfx900 ships hit the same plateau (CC:512 317.8, ZZ:1024 22.6).
The 4-real-MAC-per-complex-MAC ALU cost is irreducible — the complex MAC loop
is exactly four `v_mac_f32`, `KernelWriterAssembly.py:14975-14978` — so the
shortfall is **memory/occupancy**, not instruction count (P §2, reopened
2026-10-09). Working mechanisms, in order of confidence: 8/16-B LDS elements at
LdsPad=0 (bank conflicts — small pads {1,2,4} never benchmarked); the 2×
register footprint under PGR=1 everywhere (PGR=0 never shipped on complex);
GSU=1 everywhere (complex GSU>1 is validator-legal via MultipleBuffer,
`SolutionStructs.py:2958-2976/3543-3553`); Z stuck at VW1. Resolution path:
Group C pads → GSU wave-fill → PGR/NLCA — the wall is **open** until those land,
not "by construction".

**M4 — suppressed clock.** The newest run measured at 1.175 GHz
(`native_clock_coverage: 0.53`) ≈ **1.53× slow** vs 1.8 GHz reference. Its
absolute values are NOT comparable to the floor; its **within-run wins are
valid** (CC:512 WGM8 315.4 > WGM4 300.9, same clock). Verdict rule: judge
within-run-relative only; pin sclk (~1400 MHz) or clock-normalize before any
cross-run number.

**Honest scoreboard (typecode-filtered, folded db, re-measured 2026-10-12):
30 cells shared native-vs-floor (C §tool); 29 native / 1 floor.** The single
floor win was **CC:256** (native 193.8 vs floor 214.0, floor **+10.4 %**) —
outside the ±2 % tie band. **Superseded 2026-10-15:** the native CC:256 reading
was depressed by a candidate-pool sweep-order defect (256³ measured immediately
after 2048³; `results.md` §13.4 / `potential_configs.md` F1). The clean re-run
`run_20261015_041159` reads CC:256 as **TIE** (native 210.772 vs floor 214.882,
−0.74 %), leaving no strict floor win. (The pre-fold snapshot read 22 native / 8
floor; seven of those floor "wins" were inside the ±2 % tie band.)

## 6. Occupancy model vs emitted reality (todo 1 DONE)

`occupancy_feasible` (`oto/tensile/gates/occupancy.py`) models
`accVGPR = TT0·TT1·weight` against the per-thread accumulator budget
**`ACCVGPR_BUDGET = 128`** — weight-8 complex: TT 4x4 = 128 accVGPR passes
(measured 154–167 VGPRs/thread), TT 8x4 = 256 accVGPR fails (measured 271 =
Tensile's dead byte-identical rejection). The model's calibration tables
(weights, budgets, measured totals) live in `oto/tensile/gates/vgpr_model.py`;
the model narrative is the `occupancy.py` module docstring. Measured reality was
verified over the whole run corpus with `oto/harness/measure_vgprs.py`
(llvm-readelf on Tensile's emitted assembly objects — CPU only, no GPU). Median
measured totals per (dtype, TT):

| | 2x2 | 4x2 | 2x4 | 4x4 | 4x8/8x4 | 8x8 | 8x16/16x8 |
|---|---|---|---|---|---|---|---|
| S | 26 | 43 | 43 | 47 | 77/79 | 119 | 199 |
| D | 39 | 53 | 53 | 79 | 131 | 215 | — |
| H | 21 | — | — | 35 | 57 | 65 | 105 |
| C | 39 | 59 | 59 | 79 | 134 | — | — |
| Z | 71 | 99 | 99 | 167 | —(kernels never emitted) | — | — |

Invariant (tested): **gate-legal ⇔ measured total < 256**. Z 8x4/8x8 objects are
absent from the corpus exactly because Tensile refused to emit them — the model
and reality agree on every observed outcome. Regression:
`tests/test_occupancy_gate.py::TestMeasuredRule::test_corpus_measured_totals_agree_with_gate`.

> 2026-10-09: for the physical per-cell **resident-workgroup** audit (the
> "occupancy ≤3 everywhere" question, incl. the VGPR-vs-LDS binder split and
> the single-buffer probe), see `potential_configs.md` §5 +
> `python3 -m oto.harness.occupancy_audit`. `occupancy_feasible` gates legality;
> the audit answers residency.

## 7. Floor deck: gate-legality of the steal (todo 3 DONE)

`python3 check_candidates.py --floor` sweeps all **6 855** shipped gfx900
manifest kernels (`gfx90c_results/gfx900_shipped_manifest.json`, 84 `.dat`
entries; rebuilt into configs via `oto/tensile/library.py:shipped_kernel_config`)
through the same CPU-only preflight the deck must pass. `oto/checks/candidates.py`
owns the scope and the gate order (illegal knobs → tile divisibility → assembly
class → classic-load divisibility → LDS footprint → register-file occupancy).
CLI: `--deck <yaml>`, `--family SS`, `--quiet`, `--json <out>`; exit 1 on any
failure. Results (re-measured 2026-10-12):

- **All 30 per-cell floor WINNERS pass every gate** — the floor's winning
  configs are natively stealable. `_occupancy_margin()` prints
  `wg/cu=N acc=…vgpr …% of 64K file` for each passing config.
- Whole-deck residue **1 464/6 855 (21 %)** is generator-rule artifacts on
  non-winning shipped entries: load/divisibility **966** (VW-must-be-≥2-for-half
  462, GLVW-shift-ptr 441, totalElements 60, WG-threads 6, TT-not-multiple-of-VW
  6), assembly-class **363** (half GSU with f32 accumulate / AF0EM), occupancy-LDS
  **135** (genuine: kernels Tensile compiled for 64-KB-LDS gfx900 that the APU's
  16-KB-WG budget rejects; those never won a cell).
- An older snapshot quoted 738/357/72 for the three families; the gate/DB
  rebuild re-measured the split above. The total 1 464/6 855 (21 %) is unchanged.

Spoof-steal rule (sanctioned): take the floor's winning config per cell, adapt
for gfx90c (16-B cap / LDS budget — the gate does this), document, benchmark in
TTY. Only cell in scope was **CC:256**; it now reads **TIE** after the
2026-10-15 sweep-order fix (`results.md` §13.4), so no LOSS remains to close.

## 8. Knob deltas native vs floor — what actually differs (todo 4 DONE)

`oto/harness/cell_knob_diff.py` prints, per cell, both winners' short names,
their `STRUCTURAL_KNOBS` (MacroTile, ThreadTile, WorkGroup, GlobalSplitU,
DepthU, VectorWidth, GlobalLoadVectorWidthA/B) and the ±% delta, read from
`gfx90c_results/analysis/kernel_db.json` (rebuild with
`python3 -m oto.harness.kernel_db --rebuild`). CLI: `--family SS`,
`--floor-wins-only`, `--json out.json`. Re-measured 2026-10-12: **30 cells
shared; 29 native / 1 floor** (superseded 2026-10-15 — the one floor win,
CC:256, is a sweep-order artifact and reads TIE on the clean re-run; see below).
Findings (same kernel name almost everywhere; the deltas are the subtle ones):

- **CC:256 — the former floor win (now TIE).** Native
  `Cijk_Ailk_Bjlk_CB_MT32x32x8_SN_K1` (MacroTile 32×32, TT 4×4, VW2, GLVW 2)
  **193.8** vs floor `Cijk_Ailk_Bjlk_CB_MT64x64x8_SN_K1` (MacroTile 64×64,
  TT 4×4, VW2) **214.0** → floor **+10.4 %** (2026-10-12 db). The delta is
  **tile area** (32×32 → 64×64), not direction — both kernels are `Ailk_Bjlk`
  (NT). The native 193.8 was swept at the poisoned 256³ position (256³
  immediately after 2048³); after the sweep-order fix (`results.md` §13.4) the
  same geometry reads **210.772** vs floor 214.882 = TIE, run
  `run_20261015_041159`. (Group B; the earlier note calling this a TT-vs-NT
  direction delta is stale.)
- **SS:512/768/1365/2048** — the floor ships `128x128x8/8x8/VW4`; native now
  ships the same geometry and wins by −0.9 … −6.5 % (SS:512 854.4 vs 801.5
  −6.2 %, SS:1024 −3.1 %, SS:2048 −2.3 %, SS:4096 −6.5 % via native DepthU16 vs
  floor 8). The historical floor edge was VW4-vs-native-VW2; that gap is closed.
- **HH:1024/2048/4096** — floor `128x128x16/8x8/VW8` vs native identical;
  native −1.4 / −0.5 / −2.9 % (walls / clock margin).
- **Native wins the small cells big:** SS:256 −69.9 % (412.1 vs 124.1; native
  `96x96x16/6x6` vs floor `32x64x8/4x4`), DD:192 −71.9 % (76.1 vs 21.4),
  HH:256 −73.6 % (763.4 vs 201.5), CC:192 −62.0 % (113.8 vs 43.2), ZZ:128
  −70.8 % (16.8 vs 4.9), plus ZZ:192 −29.0 %, ZZ:256 −20.4 %, DD:256 −17.0 %,
  ZZ:512 −12.3 %, HH:512 −11.2 %.
- **Within-tie-band (±2 %) cells are walls (M1):** SS:768 −0.9 %, DD:768 −1.3 %,
  DD:1024 −1.5 %, DD:2048 −1.2 %, HH:1024 −1.4 %, HH:2048 −0.5 %, CC:512 −0.0 %;
  SS:1000/1024/1365 sit at −2.9…−3.3 % (borderline).

Never re-propose: SS 96x96x8/6x6/VW2 or HH GSU2 (dropped after prior runs;
tracked in D). Tie band ±2 %; median-of-seeds ≥ 3.

## 9. Open levers + Group status

| group | plan (P §8) | status (2026-10-09, night) |
|---|---|---|
| **A** wave-fill small cells (SS:256/512 GSU{2,4} + 64x64 alternates; HH:256/512 via 64x64 alternates **only** — HH GSU2 banned; DD:192/256 GSU probes) | TTY benchmark only | **DECKED** — SS wide tier sweeps GSU {1,2,4}; HH GSU>1 structurally banned (wide + narrow, test-locked); HH:256 + DD:256 joined `TARGET_CELLS`; **GNOME — no GPU stress here** |
| **B** CC:256 steal (NT direction + WGM8/WGM4 + LdsPadA=2 + PGR=0) | TTY | **DECKED** — pads A/B {1,2,4} + WGM8 + PGR=0 + GLVW=1 variants emit on the §9 S3 steal tile (generator `PLAN_BATCH`); ~~GSU2+workspace~~ **withdrawn 2026-10-09** (gate-refused on this port, §10.1) |
| **C** LdsPadA/B + AF0EM + StaggerUStride + StoreCInUnroll forwarding | **DONE** (writer + `ldspad_feasible` + generator `_FORWARDED` + 4 tests); CC/ZZ pad probes next | **DECKED** — CC/ZZ pad rows (A/B {1,2,4}) on the winner geometries in the seed; ZZ pads on the du8 tile only (32x32x16 winner is budget-full at 16 B/element); TTY benchmark next |
| **D** measurement hygiene (fold 005217/030033, typecode filter, VGPR measurement) | **DONE** (rebuild; 0 contamination; M tool + invariant test) | done |
| **Group C swizzle** (StaggerU/StaggerUMapping/StaggerUStride) | forwarded as a coupled trio + probed | **DECKED 2026-10-09** — the backwards `StaggerUStride` gate fixed (it refused the legal values, which is why forwarding was "blocked"); the trio is forwarded in `_write_phase_config`; swizzle probes on CC/ZZ/SS winners emit |
| **Mutator overhaul (Option H2)** | DB-hooked synthesis, wide+narrow+direction, no auto-skip, active-cell filter | **DECKED 2026-10-09** — `oto/tensile/synthesis/db.py` hooks the mutator to `kernel_db.json`; mutants bypass the identical-skip per-phase; only below-ceiling cells are mutated; the arm no longer decays or starves CC/ZZ |

### 9.1 The virgin axes — where the floor has zero variance

Cross-referencing the shipped gfx900 reference floor against Tensile's own legal
set (§1.1) gives the knobs the floor **never moves** — over the whole floor, not
merely rarely. This is the cheapest possible candidate list: every one of these
is a legal value on this device that no baseline measurement has ever occupied,
so there is no "we already tried that" to discover later. The counts are not
transcribed here on purpose (`claude.md` §5); re-derive the variance from
`python3 allruns.py` and the floor's own manifests.

**The "floor state" column is transcribed from the shipped gfx900 reference
floor's kernel census (prior-knowledge base), not re-derived here, and is marked `check`.** `allruns.py` reports the knob
values of each cell's *winner*, not the full variance across the floor, so it
cannot confirm or refute a "never moves" claim on its own. Verify a row against
the floor manifests before spending a run on it.

| knob | floor state | why it could win on gfx90c |
|---|---|---|
| `1LDSBuffer=1` | never | **halves LDS → doubles occupancy.** Requires `ScheduleInnerAccuracy` 2 or 3 |
| `DepthULdsDivisor` (2, 4) | never | cuts LDS 2×/4×. Requires SIA=3 + `TransposeLDS` + `PrefetchGlobalRead≠2` + `DirectToLds=0` |
| `LdsBlockSizePerPadA/B` | 0 everywhere | per-block padding *without* redesigning the tile; must be ≥ `unrollDepth*bpe`. Composes with `LdsPad`, which Group C already forwards |
| `WaveSeparateGlobalReadA/B` | 0 everywhere | splits the LDS buffer by wave → fewer cross-wave bank collisions (K §2 phase model) |
| `ThreadSeparateGlobalReadA/B` | 0 everywhere | `2` is documented to pair with `WaveSeparateGlobalRead` |
| `UnrollMajorLDSA/B` | 0 everywhere | relieves `VgprForLocalReadPacking`; "beneficial for smaller data types" |
| `NonTemporalA/B/C/D` (1–3) | 0 everywhere | `glc`/`slc` cache hints; on a **1 MiB L2** the pollution control is plausibly worth more than on a discrete part with 32 MiB |
| `FractionalLoad=2` | never (only {0,1}) | frees the `DepthU` choice on ragged M/N/K by moving the edge handling into a temp VGPR |
| `PersistentKernel` | 0 everywhere | amortises tile assignment; on a 4-tile grid the assignment is a real fraction of the launch |
| `MaxOccupancy < 40` | 40 | deliberately cap LDS to raise occupancy |
| `TransposeLDS=1` | 0 | TLU=0 only; aligns the LDS layout with MFMA-free VALU reads |
| `PrefetchGlobalRead=2` | 0 | deeper prefetch; conditional on the 16 384-B/WG budget |
| `GlobalReadPerMfma` / `LocalWritePerMfma` | 1 / −1 | **names are MFMA-era but the knobs are general** — they throttle global/LDS issue density, which is the thing to schedule on a machine with no MFMA |
| `LdsPadA/B = 1` | {0,2,4} (`check`) | Group C forwards pads but the domains still omit 1 |
| `StaggerUMapping` | ~0 everywhere (`check`) | Tensile's own `Perf/*.yaml` recommends `[0,1]`; the floor sits essentially entirely at the unexplored end of the vendor's own recommendation. Correctly opened in `db_knobs` |
| `NLCA = -1` | never (−1 ≠ 3) | "-1 = largest number of reads along the coalesced dimension" is the *least*-coalesced regime, a different point in the space, not a synonym |

**Caveat on the whole table.** "Zero variance in the floor" is not "safe to
turn on". Every row above changes memory traffic, LDS residency or issue
density, so each needs a paired measurement against its own baseline in the
same run — never a lone row quoted against a different run's number (M4). And
`PrefetchGlobalRead=2`, `DepthULdsDivisor`, `1LDSBuffer` and `TransposeLDS`
interact with the LDS budget, so they must be gated by `ldspad_feasible` like
every other Group C knob rather than trusted.

Complex-GSU note (supersedes the earlier "MultipleBuffer wave-fill" lever):
GlobalSplitU>1 on complex is **gate-refused on gfx90c** (scheduler:1379-1382;
Tensile passes complex only via `_GlobalAccumulation`, SolutionStructs:3543-3555)
and the port does not forward `GlobalSplitUAlgorithm`/workspace — no complex
GSU rows are decked. The complex residency ladder is **pads → PGR=0 →
NLCA (3-load tiles only, i.e. 96x96x16/6x6/VW2) → split-complex**. NLCA=3 on
128-width tiles is refused (NumLoads=1).

Legacy auto-pool audit (todo 6 DONE): 560 `phase_auto_*` dirs across runs; the
auto pool is NOT marginal — it holds the native best in **13/34 cells** (38 %),
incl. HH:256 763.4, SS:1024 1135.1, SS:256 412.1, and the legacy
`phase_auto_0_{S,Z}_*` pool (run_20260920, 117 dirs) wins 10 cells via typecode
attribution. Keep them; rename legacy S/Z tokens to ss/zz at hygiene time.

## 10. Overnight `--auto` rules (TTY task)

1. Real benchmarks run in the USER's TTY — never from a GUI session
   (GNOME constraint; CPU-only PoCs are safe).
2. Generator deck: seed overlay ships **295 rows (5 curated + 290 in-grid
   candidates, regenerated 2026-10-09 night — incl. the beat-the-spoof batch:
   CC/ZZ pads, PGR/PLR/GLVW/NLCA, CC WGM8 steal-adapt, SS GSU4 wave-fill,
   HH:256/DD:256 targets, Group C swizzle probes)**. Keep the pool for the run;
   strip `phase_cand_*` ids AFTER the run to keep later runs light (mirror
   preserves them) — `oto/harness/generate_candidates.py --prune-candidates`
   (archives first).
3. Mutations are **DB-hooked** (`oto/tensile/synthesis/db.py`): every iteration synthesises
   novel wide (DB tile donors × forward draws) + narrow (single-knob deltas on
   pads/PGR/PLR/NLCA/WGM/StaggerU/GLVW) + direction (floor-steal) mutants for
   every **active** cell (below-ceiling winners only — settled cells are
   skipped). Mutants **bypass the identical-fp skip** (the auto-skip never
   applies to a mutation) and are gated + novelty-checked before emission, so
   the arm never re-measures a tried config and never decays. The old sampler
   (tile+split only, manifest-only) is the fallback when the DB is unavailable.
4. Judge within-run only; ≥3 seeds; median; ±2 % tie band; walls are ties
   (M1), not failures.
5. Acceptance = ceiling model (L §5); parity CLI exits 0; kernel_db rebuilt
   before any verdict quote.
6. New numbers must be kernel-typecode-attributable (ground-truth §3) and
   clock-flagged (M4).
7. **Sizing (10+ h, packed):** iteration 1 = deck(**40** phases, `phases.yaml`)
   + seed overlay (**295** rows = 5 curated + 290 in-grid,
   `gfx90c_results/overlays/phases.seed.overlay.yaml`) = **335 phases ≈ 6.5 h**;
   `--budget 10` → **~15–20 h**. The per-tier counts are read live — the deck
   from `phases.yaml` and the seed overlay via
   `oto/harness/generate_candidates.py` / `oto/runners/auto_prompt._read_counts`
   — never transcribed here; `--budget <hours>` governs the run. The DB mutator's
   novelty throttle keeps each mutation iteration ~1-2 h without starving the
   wall families.

## 11. How to propose the next candidate (the loop)

Everything below is CPU-only except the TTY benchmark; a proposed candidate must
pass the preflight **before** it is decked, or it dies mid-run as an opaque
Tensile error 4.

**Step 1 — pick the cell.** Read the scoreboard (§5) and `cell_knob_diff` (§8).
Tune only **active** cells: winners below their family's §5 ceiling and outside
the ±2 % tie band. Walls (M1) and settled cells are skipped.

**Step 2 — choose the knob (mechanism first).** Match the knob to the failure
mode named in §5/§11's mechanism column, not to a blind sweep:

| symptom | first knob(s) to try | where the domain lives |
|---|---|---|
| small cell idles (<25 % residency) | MacroTile/ThreadTile smaller + `GlobalSplitU ∈ {2,4}` (SS only) | `TARGET_CELLS`, `LADDER`, `NARROW_NEIGHBOURS` |
| wide VGPR-bound cell (V just over a §3 cliff) | `PrefetchGlobalRead=0`, `PrefetchLocalRead=0` | `FORWARD_KNOB_DOMAINS` |
| complex LDS bank serialization | `LdsPadA/B ∈ {1,2,4}` | `_pad_rows`, `PLAN_BATCH` |
| complex LDS/register footprint | `LdsPad ∈` the winner geometry, then PGR=0, then NLCA (3-load tiles only) | `PLAN_BATCH` |
| narrower/wider global loads | `GlobalLoadVectorWidthA/B ∈ {1,2,4}`, `VectorWidth` | `FORWARD_KNOB_DOMAINS` |
| CU–tile mapping / cache | `WorkGroupMapping ∈ {1,4,8}` | `NARROW_NEIGHBOURS` |
| K-start channel conflicts | `StaggerU/StaggerUMapping/StaggerUStride` (coupled trio) | `PLAN_BATCH` swizzle rows |
| load count per K-slice | `NLCA ∈ {1,2,3}` (only where NumLoads≥3 side-wise) | `FORWARD_KNOB_DOMAINS` |

**Step 3 — draw the candidate from a builder (do not hand-write configs).**
Three builders exist, all keyed by family/cell:

- **Tile ladders + beat-the-spoof batch** — `oto/harness/candidate_rows.py`:
  `LADDER` (per-family vetted `(MacroTile, ThreadTile, VectorWidth)` lists, e.g.
  SS starts `128x128x8/8x8/VW4`, `128x128x16/8x8/VW4`, …, `96x96x16/6x6/VW2`;
  CC `64x64x8/4x4/VW2`; ZZ `64x64x8/4x4/VW1`), `DU_VARIANTS=(8,16)`,
  `WGM_VARIANTS=(4,1,8)`, `PATTERNS` (per-family contraction patterns),
  `TARGET_CELLS` (SS `[256,512,768,1000,1024,1365,2048,4096]`, DD
  `[192,256,2048]`, HH `[256,512,1024,2048]`, CC `[192,256,512,1024,2048]`, ZZ
  `[128,192,256,512,1024]`, HH_HPA `[512,2048,4096]`, HS_HPA `[512,2048]`),
  `NARROW_NEIGHBOURS`
  (`MacroTile`, `ThreadTile`, `VectorWidth {2:[1,4],1:[2],4:[2]}`,
  `WorkGroupMapping {4:[8,1],8:[4,1],1:[4,8]}`, `GlobalSplitU {1:[2,4],2:[1,4],4:[1,2]}`),
  `PLAN_BATCH` (the 2026-10-09 batch: CC/ZZ pad rows, CC WGM8/PGR0/GLVW1/
  LdsPadA2 steal-adapts, ZZ PGR0, SS PGR0/PLR0/GLVW1/NLCA3, HH PGR0/NLCA3, the
  Group C swizzle probes).
- **Neighbour search on a harvested winner** — `CandidateGenerator.mutate_winner`
  in `oto/tensile/candidate.py`: ≤2-knob deltas over `MacroTile`, `ThreadTile`,
  `NLCA`, `VectorWidth`, `WorkGroupMapping`, `GlobalSplitU`.
- **DB-hooked synthesis** — `oto/tensile/synthesis/db.py` (`DBMutator`): WIDE
  (DB tile donors × 5 forward draws), NARROW (1–3 knobs from
  `FORWARD_KNOB_DOMAINS`: LdsPadA/B `{0,1,2,4}`, PGR/PLR `{0,1}`, GLVW A/B
  `{1,2,4}`, NLCA `{1,2,3}`, WGM `{1,4,8}`, StaggerU `{0,8,16,32}`,
  StaggerUMapping `{0,1,2}`, StaggerUStride `{0,256,512}`, DepthU `{4,8,16,32}`,
  GSU `{1,2,4}`, AF0EM `{1,2}`), DIRECTION (toward the floor winner). Donor pool
  6, 5 draws/iteration; every mutant gated + novelty-checked before emission.

**Step 4 — gate it (CPU only).** The append boundary calls
`CandidateGenerator.validate_config` (illegal knobs → tile divisibility →
assembly class → classic-load divisibility → LDS estimate → register-file
occupancy) and the launch boundary additionally calls `ldspad_feasible` for the
forwarded knobs. Deck a whole overlay with:

```
python3 -m oto.harness.generate_candidates --dry-run   # validate + count, no write
python3 -m oto.harness.generate_candidates             # write phases.seed.overlay.yaml
python3 check_candidates.py --family CC                # preflight the live deck
python3 check_candidates.py --floor                    # verify the floor is stealable
```

`--max-fp N` is an optional cap (round-robin across family/cell buckets); the
default is **no cap** — the whole emitted in-grid pool is seeded, so nothing the
builders produce is silently dropped. The run loop never applies this cap; it
only governs how many pre-built rows the seed starts with.

**Step 5 — size and run.** One phase spans all of a family's `TARGET_CELLS`
(deck semantics: one phase, many exact sizes). 40 deck phases + 295 seed rows =
335 phases ≈ 6.5 h; `--budget 10` → ~15–20 h (§10.7). Run in the TTY, judge
within-run only, ≥3 seeds, median, ±2 % tie band.

**Step 6 — record and re-tune.** Rebuild the DB
(`python3 -m oto.harness.kernel_db --rebuild`), re-run
`python3 -m oto.harness.cell_knob_diff`; a new winner changes which cells are
active, which is the next iteration's input. Never re-propose a config already
in the ledger (novelty is enforced), and never re-propose the retired tiles in
§8.
