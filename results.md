# Benchmark Results: gfx90c (Cezanne-family APU iGPU)

> This ledger inherits the frozen prior conclusions as ceiling bars (sources:
> `prior_INSIGHTS_CAVEMAN_ULTRA.md`, also absorbed in `prior_RESEARCH_ARCHIVE.md`).
> This file's `<!-- DERIVED:* -->` blocks and hand prose are preserved append-only
> (`knowledge_base.md` §10); live report artifacts are produced by `report.py`
> (`gfx90c_results/acceptance_report.json/.html`).

## 1. Run Summary
 
 - Frozen prior data (conclusions only): 40 run entries, 19 benchmark-bearing
   runs; 771 benchmark records, 111 config-group cells, 66 unique problem cells.
 - Frozen prior-derived (ceiling bars carried from the prior campaign, provenance
   `changelog.md` 2026-09-15 -- BEFORE the gfx900→gfx90c port): 3 runs / 96 valid
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

Realistic GEMM caps (authority `gfx90c_theoretical_limits.md` §5): SS ~1119 (69%),
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
  pair. Complete it via `--gfx900-reference --resume` (1,212 remaining phases), then
  `--auto` re-derives per-cell verdicts by workload cell `(family, dtype, shape)`.

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
  AND approach the per-family ceilings of `gfx90c_theoretical_limits.md` §5
  (measured utilization is the score, logged per (family, bound_class)).

## 8. Reference floor (gfx900 spoof, live)

Dedicated `gfx900_ref_20260925_152942` (deck = the pinned 2,285 shipped kernels,
ScheduleName `vega10`): **1,073 executed, 116 failed, 1,096 unattempted** (~25.6 h,
2026-09-25 15:29 → 2026-09-26 17:05). Interrupted at 1,073/2,285; resumed via
`--gfx900-reference --resume` (1,212 phases). `--auto` gates all tuning behind its
completion. Both it and the draft deck run (`run_20260920_235815`) are registered
in `gfx90c_results/registry.db`.

**Floor chain COMPLETE.** `gfx900_ref_20260926_201843_resume` (2026-09-26 20:18 →
2026-09-27 20:08) targeted the 1,212 non-completed phases: **808 completed, 404
failed**. Chain totals across base + resume: **1,881 completed / 404 unique failed
= 2,285 decided, 0 undecided** (zero overlap between the two runs' completions).
Of the 404 resume failures, 116 were retries of the base run's failures — all 116
failed again — and 288 were first attempts. No DD/CC/ZZ floor phase failed.

## 9. Resume failure triage (404, `gfx900_ref_20260926_201843_resume`)

| Bucket | n | rc | Root cause |
|---|---|---|---|
| Tensile `0 valid solutions` | 220 | 255 | Config rejected at solution enumeration. 154 `VectorWidth must be >= 2 for half`, 30 `ThreadTile not multiple of VectorWidth`, 25 GLVWA (VW4/1), 5 `totalElements 768 % (NumThreads*grvw) != 0`, 3 GLVWB, 1 GLVWA(VW8), 2 no reject line |
| Config never written | 121 | 1 | `_write_phase_config` returns early on the assembly-class gate **without writing the file**; `execute_phase` still launches Tensile on the missing path → `FileNotFoundError`. 1,091 configs exist for 1,212 targets; the 121 missing are exactly the rc=1 set |
| User skip (`'s'` keypress) | 63 | −1 | `skipped_by_user`. Not a config/hardware failure |

Family split: HS_HPA 204, SS 106, HH+HH_HPA 94. The doubled `phase_phase_*` config
naming is the consistent convention, not the fault.

## 10. Acceptance report — native arm re-armed to the whole database

**Symptom.** `run_20260926_201835`'s report was uniformly zero: every family
`measured_cells=0 / best_median=0 / coverage=0`, `per_cell_verdicts=[]`, and all 38
deck cells RED/MISSING at 0.0.

**Cause — arm-scope asymmetry.** The spoof arm resolved across the whole reference
chain (1,881 cells), but the native arm read only the reported run. That run
executed only 8 non-duplicate phases (`402` were `identical_fp_already_passed`) and
**all 8 failed** with `Generating kernel source resulted in error 4`, which Tensile
maps to `overflowedResources == 4` = **Occupancy limit** in the ZZ/double assembly
kernel writer. Zero native cells in-run → empty analytics → deterministic zeros.
The real native winners were sitting in older runs the report never consulted.
**Fix.** The native arm is now the **whole database** — every `run_*` dir's CSVs plus
every registry `benchmark_result` row — so winners (including prior older winner runs)
are picked across all history, exactly as the spoof arm already was. Each verdict cites
the run/phase that produced the winning kernel.

**Delta semantics (corrected twice).**

*First bug.* The original code computed `delta_pct` from the cell's **max raw sample**
while the table displayed **medians** — the columns never reconciled (CC 192 displayed
31.4 vs 31.5, a −0.3% ratio, but reported −6.1% from underlying 40.49 vs 43.12). Every
statistic is now **per-kernel-median-first**, so a single lucky seed cannot decide a
verdict. Kernel medians are also keyed by source run, so the same
`(phase_id, fingerprint)` benchmarked by two runs is no longer pooled into one median.

*Second bug.* The two rendered columns were still hard-wired to "Best native median" /
"Spoof median" regardless of the basis in use, so switching basis re-broke the
guarantee. The columns now render `native_value` / `spoof_value` — the two operands
actually divided — under basis-aware headers, so the displayed ratio always equals the
printed delta (verified: 0 mismatches in JSON and in all 38 HTML rows, residual ≤0.44pp
= 1-decimal display rounding).

**Comparison bases** (`--native-agg`), per (family, dtype, shape) cell:

| agg | native vs | Question it answers |
|---|---|---|
| `winner` **(default)** | **best** vs **best** | does the deck's best kernel beat the floor's best kernel? (drop-in replacement) |
| `winner_clock` | best vs best, telemetry-adjusted | same, after normalizing each kernel to a common core clock |
| `median_clock` | median vs median, telemetry-adjusted | central tendency, clock-normalized |
| `floor_best` | native **median** vs floor **best** | can a *typical* native kernel beat the best kernel the floor ships? |
| `strict` | native **worst** vs floor **best** | does *every* native kernel beat the floor's best? (per-cell dominance) |
| `best_median` | native best vs floor **median** | lenient: deck winner vs a typical floor kernel |
| `median` | both medians | symmetric central tendency |
| `throttle` / `best` | sclk-stamped feed / max raw sample | legacy; `best` is seed-noisy, reference only |

**`winner` (best vs best) is the default** — it is the drop-in-replacement question:
you replace one shipped kernel with one native kernel, so the two candidates must be
each arm's best. Every statistic is per-kernel-median-first, so "best" means the best
*kernel* measured over its seeds, not the single luckiest seed.

**Telemetry adjustment (`*_clock` bases).** GFLOPS is linear in core clock, so each
kernel's median is scaled by `sclk_ref / sclk_measured`, where `sclk_measured` is that
phase's own sustained clock and `sclk_ref` is **one shared corpus-wide constant**
(1800 MHz, the highest clock the GPU held in this corpus) so neither arm is rescaled in
its own favour. Two guards make it refuse to lie:

1. **Idle floor is not a measurement.** A phase whose only busy samples sit at the
   400 MHz idle clock is dropped rather than scaled — scaling it by 1800/400 = 4.5x
   let a 20.7 GFLOPS kernel "win" a cell at 93.0 GFLOPS. Genuinely throttled phases
   (0.9-1.2 GHz, 158 of 770 in the resume run) are real and are kept.
2. **Coverage gate (`CLOCK_MIN_COVERAGE = 0.5`), applied symmetrically.** A clock-adjusted
   *best* is only comparable if drawn from the same population as the unadjusted best.
   At 9% coverage (the CC cells) the eligible subset is unrepresentative and its max sat
   52-67% below the unadjusted max, which flipped CC to native wins. Below the gate both
   arms fall back together to the unadjusted twin of the requested basis
   (`winner_clock` -> `winner`, `median_clock` -> `median`) and the cell is reported
   `clock_adjusted: false`.

**The native arm has no usable clock data, so `*_clock` is currently inert.**
`run_20260919_213727` (4,896 of the 6,790 native records) has **no telemetry file at
all**; `run_20260920_235815` has 458 rows, all at the 400 MHz idle clock, 0% busy and
from a sampler that predates per-phase tagging. Native clock coverage is therefore
**0.000 on all 38 cells**, and every `*_clock` run correctly degrades to its unadjusted
twin with a printed warning. The spoof arm is well covered (mean 0.74, 1,719 phases
tagged), so the machinery is real and verified — it simply cannot be applied
symmetrically until native is re-benchmarked by a sampler that tags `phase_id`
(`telemetry.py` already writes it; `run_20260920_235815`'s file just predates that
change). Adjusting only the spoof arm would deflate the floor and flatter the deck, so
the gate forbids it.

The adjustment was verified against an independent recompute from the raw
`2_BenchmarkData` CSVs plus the telemetry timelines: **38/38 cells match** on both the
raw best per-kernel median and its clock-normalized twin.

**Assumption to keep in mind:** throughput ∝ core clock holds for ALU-bound kernels but
over-corrects memory-bound ones (GFM/GEMM small shapes are limited by mclk/DRAM), so a
clock-adjusted delta on a DDR-bound cell is an extrapolation. Both the adjusted and
unadjusted statistics are emitted per cell for exactly this reason.

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
current per-cell aggregation cannot express — see `implementation_plan.md`.


<!-- DERIVED:summary -->
<!-- /DERIVED -->
<!-- DERIVED:bests -->
<!-- /DERIVED -->
<!-- DERIVED:shared -->
<!-- /DERIVED -->
## 11. ZZ dead tiles replaced — why and what it proves (2026-09-27)

**Measured fact.** All 8 executed `run_20260926_201835` phases failed
`Generating kernel source resulted in error 4` = `overflowedResources == 4` =
Tensile's *Occupancy limit* (register-file exhaustion,
`Tensile/KernelWriterAssembly.py:15422`), covering exactly `MT 128x64x8/8x4` and
`MT 64x128x8/4x8` across all 4 contraction patterns. This is **not** a launch
failure and **not** the benign "error 3" (half-store) note.

**Why the preflight missed it.** `scheduler._estimate_occupancy` derived the thread
count from `ThreadTile` via a `64 // tt` heuristic, ignored `MacroTile`, and never
counted VGPRs — so it returned ≥ 1 for every config and could never fire. The gap was
in the gate, not the tile choice.

**Proof the new gate is correct, not just stricter.** Running
`scheduler.occupancy_feasible` over the pre-fix 410-phase manifest rejects **exactly
those 8 phases and nothing else** — 402 true negatives, 8 true positives, zero false
positives. All 9 observed pass/fail calibration cases reproduce. Regression-locked in
`test_occupancy_gate.py` (18 tests) against the archived
`archive/phases.yaml.pre-occupancy-gate.bak`.

**Deck outcome.** 410 → 418: the 8 dead phases removed, 16 gate-legal ZZ phases added
(`128x32x8/8x4`, `32x128x8/2x8` as same-aspect replacements; `64x64x8/4x2` and
`128x32x16/8x4` as new axes) × 4 contraction patterns. Shipped manifest is now
**418 phases**, all gate-clean. Full derivation: `potential_configs.md` §5.7.

**Honest limit — this is a legality result, not a performance result.** No GPU was
run. ZZ is **legal but unbenchmarked**; whether any of the new tiles actually beats
the floor is unknown and can only be settled in a TTY session. The weights are
calibrated to observed outcomes, not derived from a register allocator.

<!-- DERIVED:sclk -->
<!-- /DERIVED -->
<!-- DERIVED:candidate -->
<!-- /DERIVED -->
<!-- DERIVED:budget -->
<!-- /DERIVED -->