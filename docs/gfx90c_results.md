# Benchmark Results: gfx90c (Cezanne-family APU iGPU)
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


> **GOLDEN EXAMPLE (gfx90c) — do not edit for a new device; copy the template instead.**

> **gfx90c-specific.** The generic per-device measured-evidence document
> lives in `docs/results.md` (template for the agent); this file is the
> gfx90c golden example.

> **Corpus caveat:** the live-ledger sections of this page describe the
> author's machine's `gfx90c_results/registry.db` — gitignored local state,
> not a reproducible artifact. A fresh clone has an empty ledger; the frozen
> prior-derived numbers (sections marked frozen) are the only ones that ever
> meant something outside this machine.

> This ledger inherits the frozen prior conclusions as ceiling bars (sources:
> `docs/gfx90c_tuning_guide.md` §14 (`archive/prior_insights.md`, untracked), also absorbed in `docs/gfx90c_tuning_guide.md` §14 (`archive/prior_research_archive.md`, untracked)).
> This file's hand prose is preserved append-only
> (`docs/gfx90c_knowledge_base.md` §10); live report artifacts are produced by `oto/metrics/acceptance_report.py`
> (`gfx90c_results/acceptance_report.json/.html`).

## 1. Run Summary
 
 - Frozen prior data (conclusions only): 40 run entries, 19 benchmark-bearing
   runs; 771 benchmark records, 111 config-group cells, 66 unique problem cells.
 - Frozen prior-derived (ceiling bars carried from the prior campaign, provenance
   `docs/changelog.md` 2026-09-15 -- BEFORE the gfx900→gfx90c port): 3 runs / 96 valid
   kernel-size measurements across phases 20, 25, 31.
   - Max (prior) 928.0 GFlops (83% of 1119 ceiling) on $1365^3$ SGEMM NT (`MT96x96x16`);
     Phase 20/25/31 medians 601.5 / 505.7 / 591.6 GFlops -- carried ceiling bars only.
   - **Live ledger (port era, authoritative, `gfx90c_results/registry.db`):** 3 runs,
     8,687 records (4,896 benchmark_result + 3,791 general); all measured rows are
     stamped `cell_key`/`arm`/`kernel_key`. Draft deck run
     `run_20260920_235815` (1 executed / 258 skipped) and the reference floor run
     `gfx900_ref_20260925_152942` (see §8). The archived interrupted run
     `run_20260915_001704` (1,652 records) lives in
     `archive/gfx90c_results/registry.db`. Live reports:
     `gfx90c_results/acceptance_report.json/.html`.
 - Corpus shape (raw counts intentionally omitted — no corpus count in prose,
   `claude.md` §5): families SS, HH, DD, CC, ZZ, HH_HPA, HS_HPA (+ auto
   variants); shapes 256³, 512³, 768³, 1000³, 1024³, 1365³, 2048³, 4096³.

## 2. Per-Phase Winners (carried ceiling bars)

- FP32 best: 1118.7 @1024³
- FP16 best: 2492.1 @4096³
- BF16 best: 1108.5 @2048³
- INT8 best: 881.2 @2048³
- FP64 best: 98.6 @1024³ = 98% of a 101-peak pipe (saturated).

All are frozen measured results, carried as ceiling bars only; the live ledger
below is the current data.

## 3. Ceiling utilization vs single-rate peaks

| DT | Peak (GFLOPS) | Best measured | Util |
|---|---|---|---|
| FP32 | 1613 | 1118.7 | 69% |
| FP16 | 3226 | 2492.1 | 77% |
| BF16 | 1613 | 1108.5 | 69% |
| INT8 | 1613 | 881.2 | 55% |
| FP64 | 101 | 98.6 | 98% |

Realistic GEMM caps (authority `docs/gfx90c_theoretical_limits.md` §5): SS ~1119 (69%),
DD ~98.6 (98%), HH ~2461 (77%), BF16 ~1109 (69%), INT8 ~881 (55%); ZZ/CC/HH_HPA/
HS_HPA derived ~1119/98/1119/1119. FP32/FP16/BF16 large-squares are near their
measured bars; INT8 has the most headroom (candidate wins already +18.3% at
1024³); FP64 is done.

## 4. Native vs Spoof (carried baseline to beat)

- The only same-run native-vs-spoof pair (frozen): 11 common cells → native win =
  0 / tie = 11 / loss = 0 at ±5% (largest +4.2% BF16 768³).
- Port mechanics: native build + Phase-0 10/10 + anti-alias 0 gfx900 leak + synthesis
  PASS. This is the baseline to beat.
- Action: the dedicated floor chain (`gfx900_ref_*`) supersedes the frozen same-run
  pair. Complete it via `oto bench --resume` (the flag was spelled `--gfx900-reference` then; 1,212 remaining phases), then
  `oto tune` re-derives per-cell verdicts by workload cell `(family, dtype, shape)`.

## 5. Candidate suite A–G (carried verdicts)

5W / 10T / 6L over 21 shared cells: B GEMV 32x4096x1 +13.6% and 64x4096x1 +21.3%;
D 2048³ +14.1/+20.1%; E int8 1024³ +18.3%; A sgemm 2048³ stable. Losers: A hgemm,
E bf16 @1024³, D 512/1024³. C crashed (fix pending scoped re-test). F = 3 new cells.

## 6. Log-Warning Verdicts & Known Gaps

- Envelope ±23–31% raw ALU swing; ±6–19% DDR; sclk ruler ±0–14.3% on the 7 telemetry
  runs. Verdicts must be ruler-adjusted, median-of-seeds, NumBenchmarks ≥ 3.
- Telemetry gaps are gaps; no invented measurements.
- Auto-retire: 3 record lines exist from a single invocation; do not trust until
  ≥2 independent runs/cell gating (P0-4).

## 7. Overnight / operational notes

- No out-of-footprint cells are scheduled under the oto contract (the shipped
  suite is the entire footprint).
- FP16/BF16-DDR rulers absent by design (no control cell exists yet).
- oto acceptance: beat the gfx900-spoof floor across the whole shipped suite
  AND approach the per-family ceilings of `docs/gfx90c_theoretical_limits.md` §5
  (measured utilization is the score, logged per (family, bound_class)).

## 8. Reference floor (gfx900 spoof, live)

Dedicated `gfx900_ref_20260925_152942` (deck = the pinned 2,285 shipped kernels,
ScheduleName `vega10`): **1,073 executed, 116 failed, 1,096 unattempted** (~25.6 h,
2026-09-25 15:29 → 2026-09-26 17:05). Interrupted at 1,073/2,285; resumed via
`oto bench --resume` (the flag was spelled `--gfx900-reference` then; 1,212 phases). `oto tune` gates all tuning behind its
completion. Both it and the draft deck run (`run_20260920_235815`) are registered
in `gfx90c_results/registry.db`.

**Floor chain COMPLETE.** `gfx900_ref_20260926_201843_resume` (2026-09-26 20:18 →
2026-09-27 20:08) targeted the 1,212 non-completed phases: **808 completed, 404
failed**. Chain totals across base + resume: **1,881 completed / 404 unique failed
= 2,285 decided, 0 undecided** (zero overlap between the two runs' completions).
Of the 404 resume failures, 116 were retries of the base run's failures — all 116
failed again — and 288 were first attempts. No DD/CC/ZZ floor phase failed.

## 9. Resume failure triage (404, `gfx900_ref_20260926_201843_resume`)

| Bucket | n | rc |
|---|---|---|
| Tensile `0 valid solutions` | 220 | 255 |
| Config never written | 121 | 1 |
| User skip (`'s'` keypress) | 63 | −1 |

The rc=255 bucket is Tensile rejecting configs at solution enumeration; its
per-failure breakdown is archived in `docs/changelog.md`. The rc=1 bucket is
`_write_phase_config` refusing before it writes the file — the mechanism and the
121-config gap are owned by `oto.tensile.config_writer`. rc=−1 is
`skipped_by_user`, not a config or hardware failure.

Family split: HS_HPA 204, SS 106, HH+HH_HPA 94. The doubled `phase_phase_*` config
naming is the consistent convention, not the fault.

### 9.1 Floor triage tiers (`gfx900_ref_20260926_201843_resume`, keyed by `phase_key()`)

The 1,881 resume failure set was triaged into three action tiers:

| tier | n | action | outcome |
|---|---|---|---|
| `T1_RERUN` | 127 | staged first, mandatory; `oto tune` blocks until done | 0 remain |
| `T2_RERUN_HELD` | 1,881 | opt-in only; the mechanism landed and is tested, the staging decision was withheld | deliberately NOT run (re-measuring correct kernels for no correctness gain); the floor keeps default-resolved measurements |
| `T3_UNREPRODUCIBLE` | 277 | never staged, terminal | 154 half-input kernels pinned to VW1; 121 refused by `assembly_class_valid()`; 2 with no resolvable schedule — the vendored Tensile cannot reproduce these and benchmarking a different computation instead is worse than a documented gap |
| `T0_KEEP` | 0 | reused | — |

127 + 1,881 + 277 = 2,285. `phase_id` is not safe as identity (328 of 2,285 change when the deck is rebuilt after the config fixes); every triage decision keys by `tlib.phase_key()` (hash of the shipped solution name), never by phase_id. The T1/T2/T3 statuses are code, owned by `oto.tensile.shipped_floor_manifest` (`TIER_FIRST`/`TIER_LAST`/`TIER_HELD`, `apply_rerun_tiers(..., release_held=)`).

## 10. Acceptance report — native arm re-armed to the whole database

**Mechanism (archived).** The arm-scope fix (the native arm reads the whole
database, not one run), the two delta-semantics corrections (per-kernel-median
first; operand-named columns), the aggregation bases, and the telemetry
clock-adjustment rules (the `*_clock` twins, the idle-floor guard, and the
symmetric `CLOCK_MIN_COVERAGE` fallback) are code contracts owned by
`oto.metrics.ab_delta` (module docstring, `_collect`, `_stat`) and
`oto.metrics.ab_audit`. The original post-mortem is archived in `docs/changelog.md`.

**Measured result** (report for `run_20260926_201835`, ref
`gfx900_ref_20260926_201843_resume`), native arm = **6,790 cells from 2 runs**
(`run_20260919_213727`, `run_20260920_235815`):

| agg | WIN | TIE | LOSS |
|---|---|---|---|
| `winner` (default, best vs best) | **14** | 10 | 14 |
| `winner_clock` | 14 | 10 | 14 (gate: native clock coverage 0) |
| `median` | 23 | 7 | 8 |
| `floor_best` | 3 | 7 | 28 |
| `strict` (dominance) | 0 | 0 | 38 |
| `best_median` | 38 | 0 | 0 |

Coverage: **100% of deck cells in all 7 families** (was 0%), **0 RED / 13 ORANGE /
25 GREEN**. `overall_pass=False` on the 13 ORANGE cells and on the 28 A/B losses.

**Verdict: the deck wins 14 of 38 cells best-vs-best, and loses 14.** The losses are
modest (worst HH:4096 −14.5%, HH:2048 −14.6%, SS:2048 −15.1%) and cluster at large
shapes; the wins are large (HH:256 +272%, SS:256 +227%, HH_HPA:512 +188%). The
asymmetry is a pool-size artifact in the *wins* direction: the floor's pool averages
~303 kernels/cell vs the deck's ~75, so the floor's best is a max over a 4x larger
sample. The 3.27x win at SS:256 is not a 3x better kernel — SS:256 is memory-bound
(256³) and the floor is thin there (126 GFLOPS), so that cell mostly measures floor
under-population.

**Verdict on "truly better in every way": no — per-cell dominance holds in 0 of 38.** On the
default `floor_best` basis only 3 cells win (HH_HPA:512 +69%, HS_HPA:512 +106%,
ZZ:192 +26%); the median cell loses ~40%. Worst: SS:1024 −67%, HS_HPA:1024 −64%,
HH:2048 −52%, SS:2048 −53%. Per-cell dominance (`strict`) holds in **0 of 38** cells:
the floor's best kernel is stronger than the native deck's *worst* kernel everywhere.

**Caveat — the comparison is pool-size biased against the native arm.** The floor's
candidate pool per cell averages **303 kernels vs the deck's 75** (larger in 35 of 38
cells, e.g. DD:768 96 vs 45), so a `max` over the floor is biased upward relative to a
median over a smaller, less-tuned deck. Part of the 28 losses is that asymmetry, not
kernel quality. This also means cell-level rollups can only approximate the real
question, which is **per-config**: replacing shipped kernel X with native X'. The
decisive artifact is a per-fingerprint pairing (native X' vs shipped X), which the
current per-cell aggregation cannot express — see `docs/invariants.md`.

## 11. ZZ dead tiles replaced — why and what it proves (2026-09-27)

**Measured fact.** All 8 executed `run_20260926_201835` phases failed
`Generating kernel source resulted in error 4` = `overflowedResources == 4` =
Tensile's *Occupancy limit* (register-file exhaustion,
`Tensile/KernelWriterAssembly.py:15422`), covering exactly `MT 128x64x8/8x4` and
`MT 64x128x8/4x8` across all 4 contraction patterns. This is **not** a launch
failure and **not** the benign "error 3" (half-store) note.

**Why the preflight missed it.** The old estimator could never fire — it ignored
`MacroTile` and counted no VGPRs. The gate that owns this model is
`oto.tensile.gates.occupancy.occupancy_feasible`.

**Proof the new gate is correct, not just stricter.** Running
`oto.tensile.gates.occupancy.occupancy_feasible` over the pre-fix 410-phase manifest rejects **exactly
those 8 phases and nothing else** — 402 true negatives, 8 true positives, zero false
positives. All 9 observed pass/fail calibration cases reproduce. Regression-locked in
`test_occupancy_gate.py` (18 tests) against the archived
`archive/phases.yaml.pre-occupancy-gate.bak`.

**Deck outcome.** 410 → 418: the 8 dead phases removed, 16 gate-legal ZZ phases added
(`128x32x8/8x4`, `32x128x8/2x8` as same-aspect replacements; `64x64x8/4x2` and
`128x32x16/8x4` as new axes) × 4 contraction patterns. Shipped manifest is now
**418 phases**, all gate-clean. Full derivation: `docs/gfx90c_tuning_guide.md` §13 §2 (triage outcome).

**Honest limit — this is a legality result, not a performance result.** No GPU was
run. ZZ is **legal but unbenchmarked**; whether any of the new tiles actually beats
the floor is unknown and can only be settled in a TTY session. The weights are
calibrated to observed outcomes, not derived from a register allocator.

## 12. Locked floor + consolidated deck — A/B snapshot (2026-10-03)

Post-consolidation state. Floor is locked and no longer being re-measured;
`reference_chain()` resolves to exactly one run, `gfx900_ref_locked_52149f315d`,
built by pooling all 3802 CSVs (2194 phases) from the 3-run chain. Reproduce with
`python3 -m oto.metrics.ab_audit`.

**Reproducible band, measured rather than assumed.** Same-invocation-form pairs
give `n=26`, median ratio `0.987`, p10 `0.858`, p90 `1.113` → band **±14.2%**,
and only **53.8%** of those pairs land inside the shipped ±5% default. That
`n=26` envelope is too small and too kind to the corpus: grouping *repeats* of one
identical kernel at one identical shape under one identical form (`n=1495`
groups) gives median CV **8.1%**, p90 **27.8%**, worst single-shape **36.1%**,
worst multi-shape **75.0%**. `oto.metrics.ab_audit` now grades against
`max(cross-arm band, repeat p90) = ±27.8%`, and a verdict inside that is labelled
`within_noise`, not a result. Mismatched-form pairs (`n=4`) remain meaningless as
an A/B: median `1.374`, band ±273.7%.

**51 cells: 8 WIN / 30 TIE / 0 LOSS, 13 ungraded.** Under the old ±5% band this
read as 10 WIN / 22 TIE / 6 LOSS; under the measured ±27.8% band **every one of
those six "losses" is inside the noise and becomes TIE.** There is no surviving
evidence that the native arm is behind the floor anywhere:

| Former "loss" | native | floor | delta | now |
|---|---|---|---|---|
| `HH:1024` | 2169.6 | 2578.3 | −15.85% | TIE |
| `HH:2048` | 2258.3 | 2684.1 | −15.86% | TIE |
| `HH:4096` | 2412.1 | 2821.0 | −14.50% | TIE |
| `SS:1024` | 951.1 | 1116.9 | −14.84% | TIE |
| `SS:2048` | 1032.8 | 1216.5 | −15.11% | TIE |
| `SS:768` | 928.0 | 1105.8 | −16.08% | TIE |

All six spanned −14.5% to −16.1%, a cluster entirely inside the measured repeat
tail. They are retained in the deck as the best known solution for those cells
regardless.

Wins are concentrated where the shipped floor is weak, not where tuning is
strong: `HH:256` +1018%, `SS:256` +733%, `CC:192` +635%, `ZZ:128` +329%,
`DD:192` +308%, `HS_HPA:512` +232%, `HH_HPA:512` +228%. Every surviving win is
far outside the ±27.8% band, so unlike the former losses these are not
band-sensitive. Certainty now also requires the *same Tensile generator*, not
merely the same shape count: 11 cells are `form_mismatch` (native side from the
registry-only `run_20260919_213727`) and 13 are `missing` (native `AUTO:*` cells
with no floor counterpart). The 38-cell target matrix is covered 38/38 by the new
deck; the 51 above is every cell appearing in either arm.

### 12.1 The ~2x invocation-form swing is real, and it is larger than every graded effect

Verified end to end, from raw per-seed rows rather than from any summary:

| phase | run | form | seeds | median | max seed |
|---|---|---|---|---|---|
| `phase_ss_Ailk_Bljk_mt128x128x16_tt8x8_vw2_wgm4_alu` | `run_20260920_235815` | multi-shape | 8 | 624.5 | **658.2** |
| `phase_ss_gfx900_Ailk_Bljk_mt128-tt8-vw2-du16-gsu1-f7b2c99e` | `gfx900_ref_20260929_164544_resume` | multi-shape | 8 | 626.3 | 657.9 |
| `phase_ss_Ailk_Bljk_1000x1000x1000_mt128x128x16_tt8x8` | `run_20261002_021805` | single-shape | 8 | 313.0 | **333.0** |

The kernel is genuinely the same configuration: comparing the full derived
`2_BenchmarkData/*.yaml` solution sets of the single-shape and multi-shape phases
gives an intersection of 2 of 3 solutions, i.e. **byte-identical parameter sets**
(`MacroTile=[128,128]`, `ThreadTile=[8,8]`, `VectorWidth=2`, `DepthU=16`,
`GlobalSplitU=1`, `WorkGroupMapping=4`, identical `LDA/LDB/LDC/LDD=1000`, and
identical `TotalFlops=2e9`). Max-seed ratio **1.98x**, median ratio **2.00x**.

Clock does not explain it. Busy-only (`gpu_busy_percent > 50`) core-clock
samples from the per-run `logs/telemetry.csv` give median `sclk` **1587 MHz** for
the overnight single-shape run and **1650 MHz** for the reference run, with p90
1800 MHz in both, and a phase-window sample from the multi-shape phase sits at
1612 MHz / 70 C. That is a **4-8%** spread against a **2x** gap.

One caution that cuts the other way: within the multi-shape phase itself the 8
seeds span **370.1 to 658.2 GFLOPS**, so seed-level noise alone covers most of
the gap. The honest reading is that this kernel sits on a steep, unstable part of
the curve where form, seed, and thermal state are all entangled -- not that form
alone was isolated as the cause.

### 12.2 The same gap appears inside a single run, still confounded

Grouping on true config identity (`kernel_key`), 16 kernel+shape groups were
measured in both forms, all inside `run_20260920_235815`. For
`Cijk_Ailk_Bjlk_SB_MT96x96x16_SN_K1` at `1000^3` the two populations are
**completely disjoint**: single-shape max 394.3 vs multi-shape min 635.8, best
**855.1 vs 394.3 = 2.38x**. All 16 pairs are **identical across every derived
Tensile parameter** with identical `LDA/LDB/LDC/LDD`; both sides run 8 seeds and
the recorded medians reproduce the seed lists exactly.

Form nevertheless cannot be isolated, because it is confounded twice:

- **Generator.** The single-shape population is 94% `phase_auto_*` (Tensile
  AutoTuner); the multi-shape population is entirely `phase_ss_*`/other. No pair
  in the corpus is same-generator.
- **Time window.** In that run `phase_ss_*` executed 00:00-06:44 and
  `phase_auto_*` 06:58-09:28 -- the auto phases ran in the last 2.5 h of a 9.5 h
  sustained session, so thermal state is confounded with generator.

The gap is also not a constant offset; it peaks mid-range and **inverts sign**:
`256^3: 0.25x`, `512^3: 1.34x`, `768^3: 1.82x`, `1000^3: 2.38x`, `2048^3: 1.40x`,
`4096^3: 1.00x`.

### 12.3 Resolution: how the grading handles it

The A/B is **internally form- and generator-consistent** -- the floor is entirely
`phase_ss_*` multi-shape sweeps and the surviving wins come from multi-shape
native phases -- so the gap only bites when crossing generator families, which
the certainty tier now refuses to grade. With the band set from measured repeat
spread, the summary is: **8 large wins where the floor is weak, 30 ties, no
losses.** No verdict rests on a cross-form comparison.

Two gaps were closed by the first native run on 2026-10-05 (`run_20261005_170141`,
one phase: `phase_zz_Ailk_Bjlk_mt32x32x16_tt2x2_vw1_wgm4_alu`, cheapest legal
cell in the deck):

- **Tensile's own CSVs carry no telemetry.** Across all 8113 CSVs and 394,176 rows,
  `WinnerFreq`, `WinnerPower` and `WinnerTemperature` are 0 in every cell —
  reconfirmed on the trial phase, where all three are 0 across all 40 rows.
  Clocks only exist in the separate per-run `logs/telemetry.csv` written by
  `oto/metrics/telemetry.py`.
- **Historical telemetry had no phase attribution; new telemetry does.** The
  existing `telemetry.csv` files predate the **`phase_id`** column (not `phase`),
  so a phase's own clock could only be bounded by run-level windows. The trial
  is the first phase-resolved telemetry: **1,916 of 1,950 rows tagged** (the 34
  untagged are pre-phase startup), resolving the phase to a clock base of
  **1787 MHz, 76 °C median, 82 °C max**.
- **A third gap surfaced only because the run was cheap enough to inspect:
  `gpu_busy_percent` cannot be used to gate telemetry.** The clock base is
  derived from "busy" samples at `busy > 50%`, and that filter kept **1 of 1,916**
  samples. amdgpu reports 3–8% for short and small kernels, so the filter was
  testing saturation rather than activity; `power_uw` does not separate idle from
  loaded either (idle median 20 W, p95 28 W; clocked median 23 W, min 8 W, and
  the readings are coarsely quantised). `sclk` is the discriminator that works —
  idle sits pinned at the 400 MHz floor (1,568 of 1,916 samples), which
  `SCLK_MIN_HZ` already excludes. Gate now off by default; corpus effect is
  53,860 → 93,427 usable samples with phase coverage essentially unchanged
  (92.4% → 92.3%), so no existing verdict is overturned.

What this still cannot answer: form-vs-thermal. The 2× question needs the *same*
kernel in *both* invocation forms on the *same* cell, which is precisely the
comparison the certainty tiers refuse to grade. A single cheap phase validates
the plumbing; it does not settle the mechanism.

## 13. Corpus forensics: what has actually been varied (2026-10-14)

A whole-corpus pass over all 5757 emitted kernels (`python3 -m
oto.harness.asm_occupancy`, GFLOP/s joined against every phase's `2_BenchmarkData`)
plus the knob census (`python3 -m oto.tools.run_census`). Analysis and the resulting deck are
in `docs/potential_configs.md`; this section is the measured evidence.

### 13.1 The knob census — two knobs have only ever held one value

`python3 -m oto.tools.run_census` reports, across both arms and every cell:

```
never-exercised knobs (both arms, all cells)
  GlobalSplitU         = ['1']   <- only ever this one value
  StaggerU             = ['32']  <- only ever this one value
```

Independently, no winning config in `gfx90c_results/analysis/cells_resolved.json`
sets `PrefetchGlobalRead`, `AggressivePerfMode`, `MaxOccupancy`, `LocalSplitU`,
`BufferLoad`, `InnerUnroll`, `FractionalLoad`, `UseSgprForGRO`, `LocalRead2A/B`,
`GlobalRead2A/B`, `StorePriorityOpt`, `GlobalLoadVectorWidthA/B` or
`NumLoadsCoalescedB`. The phase-name token census over all 5757 phases finds
only `g` (4834), `mt` (4201), `vw` (1267), `tt` (1247), `w` (1211), `du` (916),
`nlc` (1) — **one phase in the whole corpus mentions NLCA**.

**Consequence:** every tuning conclusion to date, and every verdict, is a
conclusion about `MacroTile x ThreadTile x DepthU x VectorWidth x
WorkGroupMapping`. The other eleven axes have never been separated from their
defaults, so nothing in the corpus is evidence about them.

### 13.2 Measured occupancy — the "always ≤3" claim, resolved

From the emitted `amdhsa_next_free_vgpr` / `amdhsa_group_segment_fixed_size`
directives, not from a gate model. Model verified against the AMD/ORNL GFX9
table (`--check-calibration`, 10/10 rows; VGPR granule 4).

| | measured |
|---|---|
| Bound by LDS (strictly) | 61.7% |
| Bound by VGPR (strictly) | 22.4% |
| Both cap identically | 15.9% |
| Median waves/CU | 8 (= 2 waves/SIMD) |
| At ≤3 waves/CU | 121 kernels, 2.1% |
| At ≤3 resident workgroups/CU | 2810 kernels, 48.8% |
| Kernels that spill to scratch | 0 |

The two "≤3" figures are different axes and must not be substituted: a
1024-thread workgroup is 16 wavefronts, so it reads as 1 resident workgroup
while occupying 16 of the 40 wave slots. The 48.8% figure is the one behind the
"occupancy is always super low" observation; it is not a occupancy-starvation
problem, and no kernel pays a scratch-spill tax.

Per family (median waves/CU, best measured GFLOP/s): Z 4 / 24.7, D 5 / 99.9,
C 8 / 360.9, S 8 / 1340.5, H 16 / 2922.8.

### 13.3 Tile coverage — the complex families are the least searched

Distinct `(MacroTile, ThreadTile, VectorWidth)` triples measured natively:

| family | triples | distinct ThreadTiles |
|---|---|---|
| SS | 49 | 16 |
| HH | 42 | 12 |
| HS_HPA | 40 | 11 |
| HH_HPA | 36 | 11 |
| DD | 17 | 7 |
| CC | 17 | 6 |
| ZZ | 9 | 5 |

Best measured kernel per family, and the ThreadTile it uses, shows the
governing rule — the winning accumulator area scales inversely with
bytes-per-element:

| family | best tile | TT | VGPR | waves/CU | LDS | best GF/s |
|---|---|---|---|---|---|---|
| H | 128x128x16 | 8x8 | 63 | 16 | 16384 | 2922.8 |
| S | 128x128x8 | 8x8 | 111 | 8 | 16384 | 1340.5 |
| D | 32x32x8 | 2x2 | 35 | 28 | 8192 | 99.9 |
| C | 64x64x8 | 4x4 | 79 | 12 | 16384 | 360.9 |
| Z | 32x32x8 | 2x2 | 63 | 8 | 24960 | 24.7 |

The live version of this table — full geometries, not `(MT, TT, VW)` triples —
is `python3 -m oto.harness.corpus_census`; §15 records what that read settled.

### 13.4 CC:256's former LOSS was a candidate sweep-order defect — now TIE

`gfx90c_results/acceptance_report.json`, run `run_20261015_041159` (current):
**19 WIN / 19 TIE / 0 LOSS**. CC:256 reads **TIE** — native `210.772` vs floor
`214.882`, `delta_pct` −0.74 %.

The earlier LOSS (−8.7 %, run `run_20261013_214649`) was **not** a kernel deficit
and **not** the floor-telemetry gap. The native arm's winning CC tile is exactly
the floor's geometry, `MT64x64x8/TT4x4/VW2`: at 256³ it measures **225.3 GF/s**
(peak rep) in the deck's numeric-order sweep and **210.8** (median) in a
single-shape phase — both at or above the floor's 214.9. It failed to win only
because the candidate pool emitted `ProblemSizes` in **lexicographic** order
(`1024, 192, 2048, 256, 512`), putting 256³ immediately after the 2048³ kernel so
that its median absorbed the throttled clock (`claude.md` §2.0.3). The same
64x64x8 CC config reads **54–73 GF/s** at 256³ with 256 in position 4, versus
**310** at 1024³ and **348** at 2048³.

The defect was generator-wide, not CC-specific: **366 of 367** generated candidate
rows carried the scrambled order; every lexicographic-order phase in the corpus is
a candidate-pool phase and every numeric-order phase is a deck/auto phase. The
order is now defined once in `oto.tensile.shape_order` and applied at all three
producer sites (wide-row build, existing-row merge, and `_narrow_row_gen`'s
in-place merge — a third site the first pass missed), with a last-mile guard in
`config_writer.write_phase_config` that re-imposes it regardless of producer
input. Pinned by `tests/test_candidate_generator.py` and
`tests/test_shape_order.py`; the live seed overlay was regenerated in numeric
order and its generated rows reproduce `iter_candidates()` exactly.

The floor arm still carries **no** clock telemetry (`spoof_clock_coverage = 0.0`),
so `clock_adjusted` remains `False` on every cell — a standing property of the
reference chain, and therefore not the explanation of any single cell's LOSS.
The `DECISION REQUIRED` this section used to carry (floor-arm telemetry re-run)
is superseded as a closure path for this cell; the verdict bands remain user-owned.

### 13.5 Confounding that these numbers still carry

- **Cross-shape winners (other cells).** CC:256's native winner is now the
  single-shape `phase_cc_Ailk_Bljk_256x256x256_mt64x64x8_tt4x4_trialD1`, so its
  attribution is clean; several other cells' "winners" are still tiles swept for
  a different shape, so their per-cell attribution is not.
- **Clock coverage is partial on the native arm too** (0.48 for CC:256), so even
  the native side is not uniformly normalised.
- **Best-vs-best per phase spans multiple problem sizes**, so the 360.9 GF/s CC
  maximum is a max over shapes, not the 256³ result.

## 14. Latest A/B, the gate census and the tile ceilings (2026-10-18)

`gfx90c_results/acceptance_report.json`, run `run_20261018_004835` against the
locked floor `gfx900_ref_locked_52149f315d`: **20 WIN / 18 TIE / 0 LOSS**,
**0 RED / 12 ORANGE**, 9 h 03 m wall (5 h 34 m of that in phases). The report is
**PROVISIONAL** — the gfx900 reference chain did not finish and the user declined
a re-measurement — so these verdicts are indicative and must not gate a release.
The step from §13.4's 19/19 is `CC:256`: **TIE → WIN (+7.8 %)**, the R8 steal
landing.

The per-cell *reading* of these 18 ties (the mechanical `cfg_gap`, the class
tracker, and why no steal is now justified) is `docs/gfx90c_tuning_guide.md` §13 §R25/§R26;
this section is the measured evidence and the provenance.

### 14.1 The twelve ORANGE cells are the two issue-bound families

> **SUPERSEDED 2026-10-21 by §16**: the ten complex ORANGE cells were a
> **4x unit error** in the bar (the client reports complex GEMMs at 2 flops
> per MAC, so a reported complex GFLOPS is ¼ of its BLAS-8 value, and the bar
> was the BLAS-8 roof). CC and ZZ are at 80-97 % of the FMA roof; the
> ORANGE list is **three** cells. The record below is kept as it was measured
> on 2026-10-18.

`per_family_coverage`, best median per graded size, `%` of the realistic ceiling:

| family | 128 | 192 | 256 | 512 | 768 | 1000 | 1024 | 1365 | 2048 | 4096 |
|---|---|---|---|---|---|---|---|---|---|---|
| CC | — | **10.6** | **20.5** | **28.8** | — | — | **30.8** | — | **31.0** | — |
| ZZ | **17.1** | **21.1** | **22.7** | **24.7** | — | — | **24.8** | — | — | — |
| SS | — | — | **36.8** | 76.4 | 99.1 | 99.0 | 101.5 | 99.2 | 104.0 | 106.1 |
| HH | — | — | **31.0** | 68.4 | — | — | 104.9 | — | 108.5 | 111.7 |
| DD | — | 79.0 | 87.1 | 97.1 | 94.3 | — | 94.2 | 90.4 | 100.2 | — |

All 12 ORANGE cells are CC (5) and ZZ (5) plus `SS:256` and `HH:256` — the two
families whose ceiling is an *issue-rate* wall (complex = 4 real FMAs per complex
MAC with no MFMA; ZZ = FP64 at 1/16), and the two small cubes the floor serves
with a rank-1 tile. `DD` is 79–100 % (79.0 % at 192³, 87.1 % at 256³, then
90–100 %) and `SS`/`HH` at 76–112 % from 512³ up: those are closed, not lagging.

### 14.2 The gate census: 0 misses, 0 false rejections

`python3 -m oto.harness.gate_calibration --population ours`, over every phase
whose launch config is on disk: **3349 configs, 3217 built, 132 empty — 0 MISS /
0 FALSE REJECTION** (before the 2026-10-18 rules: 79 refused + **53 MISS**). The
three rules and their Tensile sources are `docs/gfx90c_tuning_guide.md` §13 §R24. The
reference population keeps its pre-existing **43 false rejections**, *all* of
them the LDS tile-footprint proxy (`LDS_BUDGET = 16384`) on large-DepthU gfx900
kernels (SS 29, DD 12, HH 1, HS_HPA 1; DepthU 16/32/64) — a reference-only story,
not a regression from these rules.

### 14.3 Confounding this section carries

- **Provisional floor.** The reference chain is a single locked run with no clock
  telemetry, so no cell's verdict is clock-normalised and the whole board is
  indicative (§13.5's standing caveat, unchanged).
- **Coverage is per-cell, not per-kernel.** Every family's graded cells are
  measured, but the *search* behind them is uneven: the registry's generation log
  shows `SS`/`HS_HPA`/`HH_HPA` at 57–88 distinct geometries per cell against
  `DD` 16, `CC` 13–16 and **`ZZ` 5** (`docs/gfx90c_tuning_guide.md` §13 §R28). A WIN on
  `CC`/`DD`/`ZZ` therefore says "this deck beat the floor", not "the family is
  exhausted".

## 15. The corpus read back as history (2026-10-20)

`python3 -m oto.harness.corpus_census` reads `kernel_db.json` as a search
history rather than a scoreboard: per `family/typecode` it reports every
structural axis value with its best seed-median, and every geometry with the
rows behind it; `--cell FAM:side` does the same for one cell next to the floor's
best. It is the CPU-only step before choosing a candidate, and the tool-side
home of the closed axes in `docs/gfx90c_tuning_guide.md` §13 §R41.

Three readings from the current corpus:

- **The HPA blocks are separate histories.** `HH_HPA` and `HS_HPA` are typecodes
  `HHS` and `HSS`, both under family `HH`. Their best geometries are
  64×128 / TT4×8 / DU16 and 64×64 / TT4×4 / DU16 (medians 1447.0 and 1441.2),
  neither of which is the HH block's 128×128 / TT8×8 winner. Read them with
  `--typecode HHS` / `HSS` or the deck spelling `--cell HH_HPA:1024`; an `HH`
  aggregate cannot see them.
- **The winner tile is not the frontier tile.** Every family's best median sits
  at the geometry its winners already use (128×128 for SS/HH, 64×64 for DD/CC,
  32×32 for ZZ), not at the frontier. Every measured geometry above 16384
  elements carries TT 16×8 or 8×16, and at SS:1024 that tile has 4 rows behind
  681.3 against the 128×128's 98 rows behind 1135.1. That is the §R40 confound;
  the frontier deck is what turns it into a clean two-factor experiment.
- **No settled axis moves a cell.** On every structural axis in the census, the
  highest best-median belongs to a value the family's winners already use; no
  untried value of a measured axis is hiding above them. This is the empirical
  half of §R41 — spend on the unmeasured frontier and the assertion axis, not on
  another value of a settled knob.

## 16. The corrected reading: three ORANGE cells, not twelve (2026-10-21)

The same corpus, re-scored. The change is **not** in the measurements: it is in
the unit the complex families are scored against.

**The finding.** Tensile's client charges **2 flops per MAC for every dtype**,
complex included (`ContractionProblem::flopCount` = `2 * DataTypeInfo::packing`,
and packing is 1 for complexSingle/complexDouble;
`Tensile/Source/lib/include/Tensile/DataTypes.hpp:177`). A complex MAC is
*executed* as four real FMAs = 8 BLAS flops, so **a reported complex GFLOPS is
¼ of its BLAS-8 value**. Every benchmark CSV proves it: `TotalFlops == 2*M*N*K`
for CC, ZZ, SS and DD alike (CC 192³ -> 14,155,776 = 2*192³). The acceptance
report compared the complex families against the **BLAS-8** roof (1613 / 101),
dividing their utilisation by four.

Three independent checks agree on the truth:

1. **The client's own numbers** (`TotalFlops = 2*M*N*K` for every family).
2. **The wall clock**: CC at 512³ takes 0.834 ms (2*512³ / 322 GFLOPS); the
   FP32 pipe needs 8*512³/1613 = 0.666 ms for the same work, so the kernel runs
   at **80 % of the FMA roof**. ZZ at 1024³ takes 87.65 ms against an 85.05 ms
   FP64 roof — **97 %**.
3. **The occupancy**: CC's winner (64×64, TT 4×4, 79 VGPRs) puts 3 workgroups
   per CU = 3 waves/SIMD, *more* than SS's 128×128 winner (119 VGPRs, 2
   waves/SIMD) — which is why complex beats SS's 69 %.

**The corrected per-family table** (client-reported GFLOPS; the bar is the
client's own unit -- 279.7 for CC, 24.65 for ZZ):

| family | 192 | 256 | 512 | 768 | 1000 | 1024 | 1365 | 2048 | 4096 |
|---|---|---|---|---|---|---|---|---|---|
| CC | **42.3** | 81.8 | 115.1 | — | — | 123.0 | — | 124.0 | — |
| ZZ | 84.4 | 90.9 | 98.6 | — | — | 99.4 | — | — | — |
| SS | 30.6 | **36.8** | 78.1 | 99.1 | 103.1 | 108.1 | 99.6 | 104.4 | 108.4 |
| HH | — | **31.0** | 68.4 | — | — | 104.9 | — | 108.5 | 111.7 |
| DD | 79.0 | 87.1 | 97.1 | 96.0 | — | 95.4 | 90.4 | 100.2 | — |

**The ORANGE list is three cells**: `SS:256` (36.8 %), `HH:256` (31.0 %) and
`CC:192` (42.3 %). Every CC and ZZ cell from 256³ up is GREEN, and the complex
families are the *best* utilised in the corpus.

**What it changes for the tuning.** §14.1's reading ("the complex cells are
issue-rate walls; the resolution path is pads/GSU/PGR") was a consequence of
the mis-scaled bar, and the work it proposed (3M/Karatsuba, split-K, the
complex knob sweep) is withdrawn: there is nothing to win at 97 % of the pipe.
The headroom is in the two small cubes plus `CC:192`, and the arithmetic of
*why* is in `docs/gfx90c_tuning_guide.md` §13 §R48.2: the winners are at 53-83 % of their
own fill-and-waste bound, so the cells are **starved, not badly tuned** -- the
same kernel that scores 412 at SS:256 scores 981 at SS:4096.

**The A/B protocol is the other half.** Nine of the fifteen ties run the
floor's *own* config on both arms, and across those identical cells the delta
spans **+1.1 % to +18.6 %** -- a 17.5-point environment band against a
±5 % verdict band, with no clock telemetry on the floor side. A verdict on an
identical cell is a measurement of the machine, not of the kernel
(`docs/gfx90c_tuning_guide.md` §13 §R47.2, §R48.5).

---

## Comparability (folded from comparability.md)

## Why this exists

The 2026-10-22 like-for-like regrade (docs/gfx90c_tuning_guide.md §13 §R50) measured the
same kernel reading **2.1–4.2x differently** under a one-problem invocation than
under the family-wide one. A verdict pairing a 1-problem measurement against a
family-wide floor measures the *protocol*, not the kernel. Corpus-wide
verification on 2026-10-23 (all 3802 floor CSVs) showed every gfx900
reference-floor phase was invoked family-wide, so `family` is the graded basis
wherever a floor is compared against.

The analyzer's own advice from that regrade: §R53 — even a 3-problem "trio"
container is swap-prone across runs at fixed problem order (one DD trio read
77.8/19.6 from one run, 30.3/80.5 from another). Pairwise thinking does not
rescue partial forms either.

## The four invocation forms

Defined once in `oto/metrics/measurement_protocol.py` (`classify`, `protocol_of`,
`like_for_like`). A record carries its invocation form as `protocol`, stamped
by the kernel_db builder; the four forms:

| form | meaning | admission |
|---|---|---|
| `family` | one invocation covered every graded cell of the family (declared list wins, so a phase that lost a shape to a Tensile rejection still classifies by what it was ASKED to run) | **admitted** to graded bases |
| `single` | exactly one problem | config evidence only; never a graded basis against the floor |
| `partial` | more than one problem but not the family cell list (trio/pair containers, narrow spans) | excluded from graded bases |
| `unknown` | not derivable (registry-only rows without recorded shape lists; unattributable family; pre-protocol-stamp caches) | excluded from graded bases |

`PROTOCOLS` is the format. Do not invent new spellings.

## The rule, as enforced today

1. **kernel_db** stamps `protocol` per record (declared shapes win).
2. **`ab_records`/`ab_audit`**: when pairing an arm's best record for a cell,
   stamped protocols must match exactly (`like_for_like`); a stamped vs an
   unstamped record is honestly *unmatched*. Two never-stamped records fall
   back to the legacy count-equality check.
3. **`coverage_map`** admits only the family protocol by default
   (`--protocol`, default `family`); `--protocol any` opts out.
4. **`regression_matrix`** — every DB row is tagged with its run id; by
   default only `protocol == 'family'` rows are admitted (`--any-protocol`
   opts out). `meta` reports `protocol` and `excluded_protocol_rows`; each
   matrix entry carries its `deck` / `floor` / `all_time` run ids.
5. **`potential_configs`** corpus section splits native vs floor counts.

## Bugs found in the triage and their disposition

| # | where | bug | fix (f6aef2c) |
|---|---|---|---|
| 1 | `oto/harness/regression_matrix.py` | every DB row admitted — single-problem rows (inflated 2-4x) won all-time cells and fed vs-floor verdicts | default like-for-like filter; `--any-protocol` opts out; rows tagged with run id; `meta` gains `protocol` + `excluded_protocol_rows`; entries carry `deck`/`floor`/`all_time` run ids |
| 2 | `oto/harness/occupancy_bounds.py` | hardcoded floor run id `gfx900_ref_locked_52149f315d` — a rename/vanish silently produced empty floor results | locked reference preferred, falls back to any `gfx900_ref_*` present, prints chosen runs; nonexistent floor → exit 1 with message; cache read uses a `with` handle |
| 3 | `oto/tools/potential_configs.py` | corpus counts mixed native and floor sides | corpus section splits native vs floor counts |
| 4 | `oto/harness/candidate_pool.py` | mutable-fallback default argument | fallback normalised via `None` sentinel |
| 5 | `oto/harness/candidate_pool.py` | unused imports (`FAMILY_SHAPES`, `_pad_rows`) | dropped |

All of the above is pinned by `tests/test_comparability.py` (8 tests: admission
rule, floor discovery, run tagging, per-side counts).

## Residual state / known gaps (honest list)

* **Pre-protocol-stamp caches classify as `unknown`** and are *not* admitted to
  graded bases unless `--any-protocol` / `--protocol any` is passed. They still
  contribute to synthesis and config-evidence hunts, flagged `unknown`. We do
  not re-stamp them retroactively — a stamp would require the YAML
  `ProblemSizes` they never carried.
* **No runtime probe of the *current* GPU clock or clock-coverage floor is
  part of admission** — the like-for-like rule is about invocation width only.
  Clock-steadiness checks live elsewhere (`ab_delta` / `analytics`).
* **Floor identity is content-based, not id-based**: the floor is defined by
  the `gfx900_ref_*` runs present in kernel_db, locked first. If your kernel_db
  has no `gfx900_ref_*` runs, the audit exits 1 rather than silently grading
  against nothing.
* **`UNKNOWN` is not a verdict.** Tools surface it; nothing here asserts it
  matches or mismatches anything.

## How to re-check after touching any of this

```bash
python3 -m pytest tests/test_comparability.py tests/test_ab_audit.py tests/test_measurement_protocol.py -q
python3 -m oto.harness.regression_matrix --help           # must show --any-protocol
python3 -m oto.harness.regression_matrix [--any-protocol]   # admit non-family protocols only for deck generation
```

If you add a new DB-reading entry point, it must adopt the same default:
`family` admits, everything else abstains, `--any-protocol` opts out — and
it must report the chosen runs and the excluded row count.
