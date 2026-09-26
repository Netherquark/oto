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

<!-- DERIVED:summary -->
<!-- /DERIVED -->
<!-- DERIVED:bests -->
<!-- /DERIVED -->
<!-- DERIVED:shared -->
<!-- /DERIVED -->
<!-- DERIVED:sclk -->
<!-- /DERIVED -->
<!-- DERIVED:candidate -->
<!-- /DERIVED -->
<!-- DERIVED:budget -->
<!-- /DERIVED -->