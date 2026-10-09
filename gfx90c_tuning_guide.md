# gfx90c Kernel-Tuning Guide — the cookbook (caveman, full)

> Plain words. Hard numbers. Every claim traceable in the repo (cite keys below).
> This file formalizes the kernel-tuning research: what the deck controls, what
> actually wins, why "nothing moved", and what to try next. Read
> `gfx90c_theoretical_limits.md` first — its §5 ceilings are the acceptance bar.
> Cite keys: **L**=gfx90c_theoretical_limits.md, **P**=potential_configs.md,
> **K**=kernel_db.json (`harness/kernel_db.py`), **O**=gfx90c_common.py,
> **D**=implementation_plan.md, **M**=harness/measure_vgprs.py,
> **C**=harness/cell_knob_diff.py. Numbers below are kernel_db post-2026-10-09
> rebuild (all runs folded), typecode-filtered, median-of-seeds per cell.

## 0. The one-line truth

The deck controls **geometry and residency**, not the pipe. Large squares are
already pinned to the ALU wall (M1). The real headroom is the **small cells**
(M2: the machine idles below 25 % residency) and the **complex codegen wall**
(M3: the only axis with a mechanism is LDS bank conflicts). Everything else is
measurement hygiene (M4: suppressed clock), not tuning.

## 1. Knob surface — what the deck actually controls

| knob | what it does | legality gate | forwarded by `_write_phase_config` |
|---|---|---|---|
| MacroTile | tile dims M×N (+DepthU in the string) | occupancy (LDS) + assembly | yes |
| ThreadTile | accumulators per thread = TT0·TT1·weight VGPRs | occupancy (VGPR) | yes |
| VectorWidth / GLVW | global-load width; **16-B hardware cap** | divisibility | yes |
| DepthU | K-depth of the LDS tile | LDS budget | yes |
| GlobalSplitU | waves over K (the M2 lever) | assembly (complex/no-MFMA) | yes |
| WorkGroupMapping | CU–tile mapping | — | yes |
| contraction pattern | Ailk_Bjlk (NT) vs Alik_Bljk (TT) etc. | — | yes |
| **LdsPadA/B** | bank-conflict pad per LDS row (M3 lever) | **`ldspad_feasible` (NEW)** | **yes (NEW, Group C)** |
| **StaggerUStride** | store stagger (M3 lever) | **`ldspad_feasible` (NEW)** | **yes (NEW, Group C)** |
| **AssertFree0ElementMultiple** | half Assembly GSU>1 legality | **`ldspad_feasible` (NEW)** | **yes (NEW, Group C)** |
| **StoreCInUnroll** | C-store unrolling | **`ldspad_feasible` (NEW)** | **yes (NEW, Group C)** |

Group C (2026-10-09): the pad/RCT knobs were silently stripped by the writer —
candidates carrying them benchmarked WITHOUT the knob (167/167 reference kernels
ship pads). Now forwarded verbatim behind `scheduler.ldspad_feasible`
(padded-LDS footprint vs 16 384-B/WG budget, StaggerUStride < DepthU·bpe,
AF0EM ≥ 1). Generator kept them (`_FORWARDED`); tests lock both.

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
| CC | 1613 | **1118.7** derived | **318.0 @512 — complex codegen wall (M3), not the roof** |
| ZZ | 101 | **98.6** derived | **24.0 @1024 — same wall** |

CC/ZZ read permanently orange until the model adds a "complex codegen cap ≈ 20 %
of roof" term (P §8.6 closed as **model**, not deck deficit).

## 3. Typecode = ground truth (attribution rule)

Kernel names, not phase-id text, decide the cell. The `phase_auto_*` pool used
to resolve family `'auto'` → dtype `'S'` and dumped HH/CC/DD kernels into the SS
cells (P §13.2: S 1024 reported **2142.55**, honest **1135.1**). Rule, enforced
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

## 4. What actually wins per family (measured kernel-type patterns, P §13.3)

| lever | winner | evidence (all-run kernel_db sweep) |
|---|---|---|
| direction | `Ailk_Bjlk` (**NT**) dominates | the only non-NT winners: DD:192 `Alik_Bljk` (TT), the DD/Z:1024 `64x32` TN pocket; the spoof is NT-everywhere too |
| MacroTile | ∝ 1/element-size: S/H 128 (96 at 256), C/D 64 (32 at 192/256), Z 32 (64x32 at 1024) | one tile serves each family's whole range |
| VectorWidth | pinned to the 16-B cap: S vw4, H vw8, C vw2, D vw1-2, Z vw1, HPA vw4 | not free; the cap is hardware |
| DepthU | 8 for S/D/C/Z, 16 for H/HPA | family-locked, not a sweep knob |
| WorkGroupMapping | 4 everywhere; **8 is a real CC lever** | CC:512 WGM8 > WGM4 within-run |
| GlobalSplitU | 1 in all winners so far | the single untested wave-fill axis (Group A) |
| register hygiene | real families saturate; complex caps at the codegen wall | M1/M3 |

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

**M3 — the Tensile complex codegen wall (CC/ZZ).** Oversubscribed residency
(91 %→1463 %) yet CC caps ≈290–318 and ZZ ≈21–24; the gfx900 ships hit the same
plateau (CC:512 317.8, ZZ:1024 22.6). Cause: complex MAC = 4–6 real
instructions, 2× register footprint, 8/16-B LDS elements amplifying bank
conflicts 2–4×, Z stuck at VW1. **No tile/pattern/GSU mutation crosses it.** The
only mechanism: the LDS-conflict knobs now forwarded (LdsPadA/B, StaggerUStride
— Group C). Swizzle/layout options remain unforwarded; that is the remaining
M3 experiment.

**M4 — suppressed clock.** The newest run measured at 1.175 GHz
(`native_clock_coverage: 0.53`) ≈ **1.53× slow** vs 1.8 GHz reference. Its
absolute values are NOT comparable to the floor; its **within-run wins are
valid** (CC:512 WGM8 315.4 > WGM4 300.9, same clock). Verdict rule: judge
within-run-relative only; pin sclk (~1400 MHz) or clock-normalize before any
cross-run number.

**Honest scoreboard (typecode-filtered, folded db, pre-tuning):** 30 cells
shared native-vs-floor (C §tool); **22 native / 8 floor**; of the 8 floor wins
only CC:256 (−13.8 % … native 188.1 vs floor 214.0) is outside the ±2 % tie
band — the single honest LOSS and the only sanctioned spoof-steal target.

## 6. Occupancy model vs emitted reality (todo 1 DONE)

`occupancy_feasible` models accVGPR = TT0·TT1·weight, budget 128 (weight-8
complex: TT 4x4 = 128 pass → measured 154–167; TT 8x4 = 256 fail → measured
271 = Tensile's dead byte-identical rejection). Verified 2026-10-09 over the
whole run corpus with `harness/measure_vgprs.py`
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

## 7. Floor deck: gate-legality of the steal (todo 3 DONE)

`python3 check_candidates.py --floor` sweeps all 6 855 manifest kernels
(rebuilt into configs via `tensile_library.shipped_kernel_config`). Results:

- **All 30 per-cell floor WINNERS pass all 4 gates** (divisibility / assembly /
  occupancy / forwarded-knob) — the floor's winning configs are natively
  stealable. New `_occupancy_margin()` prints `wg/cu=N acc=…vgpr …% of 64K file`.
- Whole-deck residue 1 464/6 855 (21 %) is generator-rule artifacts on
  non-winning shipped entries (GLVW/VW divisibility 738, assembly-class 357,
  occupancy-LDS 72 — last one genuine: kernels Tensile compiled for 64-KB-LDS
  gfx900 that the APU's 16-KB-WG budget rejects; those never won a cell).

Spoof-steal rule (sanctioned): take the floor's winning config per cell, adapt
for gfx90c (16-B cap / LDS budget — the gate does this), document, benchmark in
TTY. Only cell in scope: **CC:256**.

## 8. Knob deltas native vs floor — what actually differs (todo 4 DONE)

`harness/cell_knob_diff.py` prints, per cell, winner kernels + differing knobs.
Findings (same kernel name almost everywhere; the deltas are the subtle ones):

- **CC:256** — the steal: native `Alik_Bjlk` (TT direction) MT64x64/4x4 vs the
  floor's `Ailk_Bjlk` (NT) same geometry, 188.1 vs 214.0. Direction + WGM is the
  ~14 % delta. (Group B.)
- **SS:512/768/1365/2048** — floor wins by VW4 (GLVW4) vs native VW2; same
  MT128x128/8x8/du8 otherwise: +3.8 / +0.5 / +3.2 / +1.4 %.
- **HH:1024/2048/4096** — floor VW8-GLVW8 vs native VW8-GLVW8 (identical);
  +4.0 / +6.6 / +0.1 % — the 2048 delta is clock/margin, 4096 is a wall tie.
- Native wins the small cells big: SS:256 −69.9 % (412 vs 124 — native geometry
  96x96 vs floor 32x64), DD:192 −59.4 % (52.6 vs 21.4), ZZ:128 −70.8 % (16.8 vs
  4.9), CC:192 −62.0 % (113.8 vs 43.2), ZZ:256 −20.0 %, ZZ:512 −11.3 %.

Never re-propose: SS 96x96x8/6x6/VW2 or HH GSU2 (dropped after prior runs;
tracked in D). Tie band ±2 %; median-of-seeds ≥ 3.

## 9. Open levers + Group status

| group | plan (P §13.4) | status (2026-10-09) |
|---|---|---|
| **A** wave-fill small cells (SS:256/512, HH:256/512 via GSU2/4 + 64x64 alternates; DD probes) | TTY benchmark only | CPU-gated ready; **GNOME — no GPU stress here** |
| **B** CC:256 steal (NT direction + WGM8/WGM4 + 64x32/32x64 alternates) | TTY | CPU-gated ready |
| **C** LdsPadA/B + AF0EM + StaggerUStride + StoreCInUnroll forwarding | **DONE** (writer + `ldspad_feasible` + generator `_FORWARDED` + 4 tests); CC/ZZ pad probes next | next TTY experiment |
| **D** measurement hygiene (fold 005217/030033, typecode filter, VGPR measurement) | **DONE** (rebuild; 0 contamination; M tool + invariant test) | done |
| swizzle/layout LDS options | not forwarded yet | remaining M3 axis, after C probes |

Legacy auto-pool audit (todo 6 DONE): 560 `phase_auto_*` dirs across runs; the
auto pool is NOT marginal — it holds the native best in **13/34 cells** (38 %),
incl. HH:256 763.4, SS:1024 1135.1, SS:256 412.1, and the legacy
`phase_auto_0_{S,Z}_*` pool (run_20260920, 117 dirs) wins 10 cells via typecode
attribution. Keep them; rename legacy S/Z tokens to ss/zz at hygiene time.

## 10. Overnight `--auto` rules (TTY task)

1. Real benchmarks run in the USER's TTY — never from a GUI session
   (GNOME constraint; CPU-only PoCs are safe).
2. Generator deck: seed overlay ships 282 rows (277 in-grid); prune
   `phase_cand_*` ids (mirror already says so) to keep future runs light —
   `harness/generate_candidates.py --prune-candidates` (archives first).
3. Judge within-run only; ≥3 seeds; median; ±2 % tie band; walls are ties
   (M1), not failures.
4. Acceptance = ceiling model (L §5); parity CLI exits 0; kernel_db rebuilt
   before any verdict quote.
5. New numbers must be kernel-typecode-attributable (ground-truth §3) and
   clock-flagged (M4).