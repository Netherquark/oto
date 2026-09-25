# Knowledge Base Final — oto gfx90c Tensile Port

> Comprehensive, self-contained reference for the one-shot deterministic convergence
> campaign porting AMD Tensile BLAS library to native gfx90c (Cezanne APU iGPU).
> Generated: 2026-09-15. Data: 3,208 raw measurements across 320 unique cells.

---

## 1. Project Identity

| Field | Value |
|-------|-------|
| Project | Native gfx90c Tensile library port |
| Target ISA | gfx90c `(9,0,12)` |
| Device | AMD Ryzen 5 PRO 5650U — Cezanne APU, Radeon Graphics |
| Compute Units | 7 |
| SIMD Lanes | 448 (= 7 CUs × 64 lanes/CU) |
| Wavefront Size | Wave64 |
| SCLK | 1800 MHz |
| Memory | DDR4-3200 dual-channel (UMA with system RAM) |
| Spoof Baseline | gfx900 (vega10 schedule) — must be beaten |
| Strategy | One-shot deterministic convergence (no LLM in loop) |
| Codebase | oto/ (53KB driver + 7 supporting modules) |
| Target Coverage | 28 families × 4 patterns = 2,285 distinct shipped kernels |
| Manifest | phases.yaml (304 entries as of latest run) |

---

## 2. Hardware Reality

### 2.1 Theoretical Peaks (gfx90c)

| DataType | Peak GFlops | Formula |
|----------|-------------|---------|
| FP32 (S) | 1,613 | 448 lanes × 2 FMA/cycle × 1.8 GHz |
| FP16 (H) | 3,226 | 448 lanes × 4 FMA/cycle × 1.8 GHz |
| BF16 (B) | 1,613 | Same as FP32 effective |
| FP64 (D) | 101 | 1/16 FP32 rate |
| INT8 | 1,613 | Packed INT8 |
| Complex FP32 (C) | 1,613 | Equivalent to FP32 |
| Complex FP64 (Z) | 101 | Equivalent to FP64 |

### 2.2 Realistic Ceilings (Empirical, ~69-98% of theoretical)

| Family | Realistic Ceiling (GFlops) | Source |
|--------|---------------------------|--------|
| SS (FP32) | 1,118.7 | ~69% of 1,613 |
| HH (FP16) | 2,461.0 | ~76% of 3,226 |
| DD (FP64) | 98.6 | ~98% of 101 |
| ZZ (Complex64) | 98.6 | = DD ceiling |
| CC (Complex32) | 1,118.7 | = SS ceiling |
| HH_HPA | 1,118.7 | HPA: FP16 inputs, FP32 accumulate |
| HS_HPA | 1,118.7 | Mixed FP16/FP32 |

### 2.3 APU Constraints

- **UMA Memory**: GPU shares system RAM — bandwidth limited vs discrete GPU
- **Power**: 15-35W TDP, 24W median observed during benchmarks, 68°C median temp
- **No Dedicated VRAM**: All allocations go through amdgpu kernel driver
- **LDS**: 64 KB per CU shared local data store
- **VGPR**: 256 per SIMD, limits occupancy

---

## 3. Codebase Architecture

### 3.1 Pipeline (7 Stages)

```
Stage 1: Manifest & Phase Execution     ← phases.yaml loader
Stage 2: Candidate Generation           ← scheduler.py (CandidateGenerator)
Stage 3: Benchmark Execution            ← port_tensile.py (TensileDriver)
Stage 4: Adaptive Repeat / Convergence  ← policy.py (CellAggregation, StabilityStatus)
Stage 5: Analytics & Registry           ← analytics.py (AnalyticsEngine, CellAnalytics)
Stage 6: Synthesis / Build              ← TensileCreateLibrary (Stage 6)
Stage 7: Acceptance A/B & Final Report  ← report.py (AcceptanceReporter)
```

### 3.2 File Inventory

| File | Size | Role |
|------|------|------|
| `port_tensile.py` | 1,362 lines (53KB) | Main driver, CLI, Stage 1/3 orchestration, telemetry sampler |
| `scheduler.py` | 615 lines | Stage 2: candidate generation, config validation, knob mutation |
| `analytics.py` | 430 lines | Stage 5: cell analytics, native-vs-spoof delta, cell-status classification |
| `policy.py` | — | Stage 4: cell aggregation (N8 median-of-seeds), stability, convergence |
| `report.py` | 816 lines | Stage 7: A/B verdicts, acceptance report JSON + HTML dashboard |
| `agent.py` | — | Stage 4: ConvergenceAgent (harvest → mutate → loop), ConvergenceVerdict |
| `registry.py` | — | SQLite append-only ledger (records, phases, runs tables) |
| `telemetry.py` | — | TelemetrySampler: sysfs amdgpu sensor reader (power, temp, clocks) |
| `gfx90c_common.py` | — | Single source of truth: PEAK_GFLOPS, FAMILY_DTYPES, FAMILY_DTYPE_CHAR, FAMILY_SHAPES, REALISTIC_CEILINGS |
| `check_db.py` | — | DB inspection utility |
| `check_retirement.py` | — | Retirement records checker |

### 3.3 Key Design Patterns

- **Append-only SQLite registry**: records are never edited/deleted, only appended
- **N8 median-of-seeds**: cell performance = median of up to 8 benchmark runs per config
- **Spread ratio**: max/min across seeds — high spread = unstable config
- **Convergence loop**: harvest winners → mutate ≤2 knobs → re-benchmark → repeat
- **Retirement**: ≥3 samples per cell, ≥2 independent runs, ≤1% median drift
- **Anti-alias scan**: rejects any gfx900/vega10 tokens leaking into native output
- **Cooldown latch**: 30s thermal cooldown between GPU phases (skippable via 's')

### 3.4 Contraction Pattern → Transpose Mapping

| Pattern | TransposeA | TransposeB | Layout |
|---------|------------|------------|--------|
| Ailk_Bljk | False | False | NN |
| Ailk_Bjlk | False | True | NT |
| Alik_Bljk | True | False | TN |
| Alik_Bjlk | True | True | TT |

---

## 4. Run History

### 4.1 Current Campaign (oto)

| Metric | Value |
|--------|-------|
| Active run | `run_20260915_001704` (interrupted at 08:00) |
| Duration | ~7.7 hours (00:17 → 08:00) |
| Phase directories | 304 |
| Completed benchmarks | 292 |
| Failed benchmarks | 48 |
| Skipped phases | 972 |
| Total raw measurements | 2,400 (from current run) |
| Unique cells benchmarked | 300 |
| Registry records | 1,652 |
| Phases in manifest | 304 |

### 4.2 Archive (Prior attempts)

| Registry | Runs | Records | Completed |
|----------|------|---------|-----------|
| archive/gfx90c_results1 | 10 | 147 | 1 (run_20260913_214604) |
| archive/gfx90c_results2 | 35 | 525 | 3 |
| **Combined** | **45** | **672** | **4** |

### 4.3 Combined Dataset

| Metric | Value |
|--------|-------|
| Total raw measurements | 3,208 |
| Total unique cells | 320 |
| Families benchmarked | SS, HH, DD, CC, ZZ, HH_HPA, HS_HPA + auto variants |
| Shapes benchmarked | 256³, 512³, 768³, 1000³, 1024³, 1365³, 2048³, 4096³ |

---

## 5. Benchmark Results

### 5.1 Per-Family Best Performance (Native GFX90c ISA)

| Family | Best Median GFlops | Config | Shape | % of Realistic Ceiling | % of Theoretical |
|--------|-------------------|--------|-------|----------------------|-----------------|
| DD (FP64) | 96.48 | Alik_Bjlk MT32x32x16 TT2x2 | 2048³ | **97.8%** | 95.5% |
| HH (FP16) | 1,731.96 | Ailk_Bljk MT128x128x16 TT8x8 | 1024³ | **70.4%** | 53.7% |
| HH_HPA | 1,220.11 | Ailk_Bjlk MT128x64x16 TT4x8 | 2048³ | **109.1%** ⚠ | 75.6% |
| SS (FP32) | 671.08 | MT96x96x16 TT6x6 NLCA1 | 4096³ | **60.0%** | 41.6% |
| auto (SS-family) | 868.55 | MT96x96x16 | 4096³ | **77.6%** | 53.8% |
| HS_HPA | 764.76 | — | — | **68.3%** | 47.4% |
| CC (Complex32) | 283.47 | Ailk_Bjlk MT64x64x8 TT4x4 | 2048³ | **25.3%** | 17.6% |
| ZZ (Complex64) | 23.54 | Ailk_Bjlk MT32x32x16 TT2x2 | 1024³ | **23.9%** | 23.3% |

> ⚠ HH_HPA shows 109.1% of 1,118.7 ceiling — the empirical ceiling may be
> too conservative for this family. Best measured 1,220.11 GFlops.

### 5.2 Shape Scaling Patterns

#### SS (FP32) — Candidate C (MT96x96x16/TT6x6)

| Shape | Retest 1 Median | Retest 2 Median | Spread |
|-------|-----------------|-----------------|--------|
| 768³ | 472.3 | 465.4 | Low |
| 1000³ | 474.5 | 533.1 | Moderate |
| 1365³ | 505.0 | 492.0 | Moderate |

Peak on 1365³ hit 838 GFlops in one seed (retest 2) but median is ~490 — high variance.

#### SS (FP32) — Baseline (MT64x64x16)

| Shape | Spoof (gfx900) Median | Native (gfx90c) Median | Delta |
|-------|----------------------|----------------------|-------|
| 1024³ | 574.3 | 490.4 | **−14.6% (LOSS)** |
| 2048³ | 656.7 | 650.7 | **−0.9% (TIE)** |
| 4096³ | 659.2 | 671.4 | **+1.8% (TIE)** |

Native only ties spoof at large shapes. At 1024³, native is **worse** — the spoof
gfx900 code path happens to be better-optimized for this specific config on this APU.

#### HH (FP16) — Best Config (MT128x128x16/TT8x8)

| Shape | Median GFlops | % of 2461 Ceiling |
|-------|--------------|-------------------|
| 512³ | 1,257.8 | 51.1% |
| 1024³ | 1,732.0 | **70.4%** |
| 2048³ | 1,323.2 | 53.8% |

1024³ is the sweet spot — large enough for ALU saturation, small enough to stay in cache.

### 5.3 Below-Ceiling Cells (<50% Ceiling, ALU-Bound)

Terminology note: the old "RED-list of under-performing cells" is now ORANGE
(measured but below the 50% realistic-ceiling gate); RED is reserved for missing
contract cells. 24+ cells sit below the gate. Categories:
- **ZZ (Complex64)**: All cells < 24% ceiling — fundamentally limited
- **CC (Complex32)**: All cells < 25% ceiling — needs different approach
- **SS on non-power-of-2 shapes**: 768³, 1000³, 1365³ with MT96x96x16 hit 24-35%
- **SS small shapes**: 256³ at 22% ceiling — DDR-bound but classified as ALU
- **HH on 256³**: 630 GFlops = 25.6% ceiling — DDR-bound

### 5.4 Telemetry Profile

| Metric | Median | Peak | Hardware Limit |
|--------|--------|------|---------------|
| Package Power | 24 W | 68 W | 35 W (APU cap) |
| Edge Temperature | 68°C | 79°C | 95°C |
| Shader Clock (SCLK) | 1,800 MHz | 1,800 MHz | 1,800 MHz |
| Memory Clock (MCLK) | * | * | 1,200 MHz |

> ⚠ SCLK/MCLK/gpu_busy not readable in current sysfs setup (all reported as 0).
> Power sensor works correctly via `power1_input`.

---

## 6. Convergence Loop Analysis

### 6.1 Auto-Generated Candidates (72 phases)

All auto phases target SS dtype with a single tile configuration:
- **MacroTile**: 96×96×16 (fixed)
- **ThreadTile**: 6×6 (fixed)
- **NLCA**: {1, 3}
- **VectorWidth**: {1, 2}
- **WorkGroupMapping**: {1, 4, 8}

These represent the first iteration of the convergence loop exploring the neighbourhood
of Candidate C (the best SS config in the frozen conclusions).

### 6.2 Auto-Run Performance Distribution

| Metric | Value |
|--------|-------|
| Cells benchmarked | 72 |
| Min GFlops | 269.75 |
| Median GFlops | 458.20 |
| Max GFlops | 868.55 |
| Best config | NLCA=1, VW=2, WGM=4 at 4096³ |

### 6.3 Knob Impact (Preliminary)

| Knob | Values Tested | Impact |
|------|--------------|--------|
| NLCA | 1 vs 3 | NLCA=1 dominates for most shapes |
| VectorWidth | 1 vs 2 | VW=2 better at large shapes, VW=1 at small |
| WorkGroupMapping | 1, 4, 8 | WGM=4 or 8 better than 1 |

---

## 7. Patterns & Insights

### 7.1 Key Findings

1. **DD (FP64) is solved**: 97.8% of ceiling — no more tuning needed
2. **HH (FP16) strong**: 70.4% ceiling at 1024³, MT128x128x16 is the clear winner
3. **SS (FP32) needs work**: 60% ceiling at best, auto-loop candidates not yet converged
4. **CC/ZZ fundamentally limited**: Complex types need different approach than simple knob tuning
5. **HPA families**: HH_HPA exceeds its set ceiling (1,220 vs 1,118.7) — ceiling may need updating
6. **Shape sensitivity**: Non-power-of-2 shapes (768³, 1000³, 1365³) consistently underperform
7. **Native vs spoof parity**: Only achieved at 4096³ for SS — not yet at 1024³/2048³
8. **High variance on asymmetric shapes**: 1365³ shows 407-838 GFlops range (2x spread)

### 7.2 What Works

- MT128x128x16 TT8x8 for HH (FP16) — clear winner across all shapes
- MT64x64x8 TT4x4 for CC/DD — small tiles, low occupancy but efficient for low-throughput ops
- MT32x32x16 TT2x2 for ZZ — minimal tile, register pressure management
- NLCA=1 for most configs — Tensile auto-search finds optimal coalescing
- WorkGroupMapping ≥ 4 — wavefront scheduling benefit on gfx90c

### 7.3 What Doesn't Work

- MT96x96x16 TT6x6 for SS — the "Candidate C" underperforms at most shapes
- NLCA=3 with VW=2 — Tensile-validity fallback to NLCA=1 needed in many cases
- Large MT for DD/ZZ — register pressure exceeds benefit
- Shapes 256³ and below — DDR-bound regardless of tile config

### 7.4 Unresolved Questions

1. Is the realistic ceiling for SS (1,118.7) achievable? Or is ~870 the true max on this APU?
2. Should HH_HPA ceiling be raised to ~1,200+ based on observed 1,220 GFlops?
3. Can CC/ZZ ever reach >30% ceiling on gfx90c, or are they architecturally limited?
4. Would a non-square MT (e.g., 128×64) outperform square MT for SS at 2048³+?
5. How much does DDR4-3200 bandwidth cap FP32 scaling at 4096³+?

---

## 8. File Relationships

```
port_tensile.py ─────┬──→ scheduler.py ──→ gfx90c_common.py
                     ├──→ analytics.py ──→ gfx90c_common.py, policy.py
                     ├──→ agent.py ──→ scheduler.py, analytics.py
                     ├──→ policy.py ──→ gfx90c_common.py
                     ├──→ registry.py
                     └──→ report.py ──→ analytics.py, gfx90c_common.py

phases.yaml ←───────── scheduler.py (generates), port_tensile.py (reads)
gfx90c_results/registry.db ←── registry.py (writes)
gfx90c_runs/ ←─────────────── port_tensile.py (creates run dirs, configs, CSVs)
```

---

## 9. Data Artifacts

### 9.1 Generated Files

| File | Type | Content |
|------|------|---------|
| `unified_measurements.csv` | CSV | 3,208 raw benchmark measurements |
| `unified_cell_summary.csv` | CSV | 320 cells with median/mean/min/max/spread |
| `acceptance_report.json` | JSON | Latest acceptance report (per-family, per-cell status) |
| `acceptance_report.html` | HTML | IBM Carbon-styled dashboard with theme toggle |
| `benchmark-retirement-sensor-logging-fixes.json` | JSON | 19MB AI conversation export (1,326 messages) |

### 9.2 Archive Data

| Path | Content |
|------|---------|
| `archive/gfx90c_results1/` | 10 runs, 1 completed — initial test |
| `archive/gfx90c_results2/` | 35 runs, 3 completed — extended campaign |
| `archive/phases_20260914_*.yaml` | Phase-manifest snapshots (4) |

---

## 10. Visual Recommendations

### 10.1 Priority Visualizations

#### V1. Per-Family Ceiling Utilization (Bar Chart)
- **Type**: Grouped bar chart
- **X-axis**: Families (SS, HH, DD, CC, ZZ, HH_HPA, HS_HPA)
- **Y-axis**: % of realistic ceiling (0-120%)
- **Bars**: Best measured vs theoretical peak
- **Annotation**: Horizontal line at 100% ceiling
- **Why**: Shows at-a-glance which families need work

#### V2. Shape Scaling Heatmap
- **Type**: Heatmap
- **Rows**: Families (SS, HH, HH_HPA)
- **Columns**: Shapes (256³ → 4096³)
- **Color**: Median GFlops (log scale)
- **Why**: Reveals sweet spots and DDR-bound regions

#### V3. Native vs Spoof Head-to-Head
- **Type**: Paired bar chart / dot plot
- **X-axis**: Shapes (1024³, 2048³, 4096³)
- **Y-axis**: GFlops
- **Pairs**: Native (gfx90c) vs Spoof (gfx900)
- **Color**: Green (win), Yellow (tie), Red (loss)
- **Why**: Core metric — are we beating the spoof?

#### V4. Convergence Loop Progress
- **Type**: Scatter plot with trend line
- **X-axis**: Iteration number (1 → N)
- **Y-axis**: Best median GFlops per iteration
- **Color**: NLCA value
- **Why**: Shows if the loop is converging or oscillating

#### V5. Knob Sensitivity Analysis
- **Type**: Box plot or violin plot
- **Groups**: NLCA (1 vs 3), VW (1 vs 2), WGM (1 vs 4 vs 8)
- **Y-axis**: GFlops
- **Facet**: By shape size
- **Why**: Identifies which knobs matter most

#### V6. Spread Ratio Distribution
- **Type**: Violin/box plot
- **X-axis**: Families
- **Y-axis**: Spread ratio (max/min across seeds)
- **Highlight**: Spread > 2.0 flagged as unstable
- **Why**: Reveals config stability — high spread = unreliable

#### V7. Power-Temperature Profile Over Time
- **Type**: Multi-axis time series
- **X-axis**: Time
- **Left Y**: Power (W)
- **Right Y**: Temperature (°C)
- **Overlay**: Phase boundaries (vertical lines)
- **Why**: Thermal throttling detection, power budget analysis

### 10.2 Secondary Visualizations

- **V8**: Tiered benchmark waterfall (all 320 cells ranked by GFlops)
- **V9**: Per-kernel-name performance distribution (violin plot by kernel name pattern)
- **V10**: below-ceiling cell scatter (x = shape complexity, y = % ceiling, color = bound class)

### 10.3 Data Sources for Visualization

All data available from:
- `unified_measurements.csv` — raw measurements (V1-V6, V8-V10)
- `unified_cell_summary.csv` — aggregated cell stats (V1-V6)
- `gfx90c_runs/run_*/logs/telemetry.csv` — telemetry time series (V7)
- `gfx90c_results/acceptance_report.json` — acceptance verdicts (V3)

---

## 11. Overnight `--auto` Convergence Run — Run_20260915_001704 (5 iterations, interrupted)

### 11.1 Run Identity & Outcome

| Field | Value |
|---|---|
| Run ID | `run_20260915_001704` |
| Command | `port_tensile.py --auto` (auto-convergence loop, budget=100 default, mutation_budget=2) |
| Started / Ended | 00:17:04 / 07:58:46 (SIGINT-style stop) |
| Status | **interrupted** |
| Registry | 1,652 records: completed=292, failed=48, skipped=972, started=340. **0 retire records** |
| Iterations reached | 5 full pass cycles before interruption |

### 11.2 Iteration Timeline (reconstructed from registry timestamps)

`run_auto` iteration 1 starts a full "pass" over the phase list, then re-loops. This run performed 5 passes:

| Pass | Window | Started | Completed | Failed | Skipped | Notes |
|---|---|---|---|---|---|---|
| 1 | 00:17→05:36 | 232 | 220 | 12 | 0 | Initial family manifest (232 phases); 12 `hs_hpa` fail; deduct phase list to 292 candidates, 72 auto appended |
| 2 | 05:36→07:30 | 84 | 72 | 12 | 220 | 72 auto phases all run (05:49–07:28); family skipped as `identical_fp`; hs_hpa fail again |
| 3 | 07:30→07:44 | 12 | 0 | 12 | 292 | Pure retry loop; everything skipped or hs_hpa failing |
| 4 | 07:44→07:58 | 12 | 0 | 12 | 292 | Same pattern |
| 5 | 07:58→07:58:46 | 0 | 0 | 0 | 168 | Interrupted mid-pass |

**Key observation**: after pass 2, the run became a **stall loop** — no new candidates, nothing new run (292 skip/fail per pass), it just re-harvested, re-mutated, and found nothing new to do, spinning until interrupted.

### 11.3 The Auto Sweep (72 phases = 9 knob variants × 8 shapes)

All auto phases are fixed **MT96x96x16 / TT6x6**. The 9 variants canvassed are:

| Variant IDs | NLCA | VW | WGM |
|---|---|---|---|
| #4, #43, #42 | 1 | 2 | 4, 1, 8 |
| #38 | 1 | 1 | 4 |
| #9, #8, #6 | 3 | 2 | 1, 8, 4 |
| #46 | 3 | 1 | 8 |
| #47 | 3 | 1 | 1 |

Shapes: 256³ (CC) + SS 512³, 768³, 1000³, 1024³, 1365³, 2048³, 4096³. All 72 completed with 8 seeds each = 576 measurements. No `phase_auto_1+` ever appeared in the registry — all 72 rows are `phase_auto_0_*` (agent iteration 0 in name).

### 11.4 Auto Results vs SS-Family Best (median GFlops, last CSV column)

| Shape | AutoBestVar | AutoMed | SSFamMed | Δ% | Winner |
|---|---|---|---|---|---|
| 256³ | var#9 | 416.1 | 328.0 | +26.9% | auto |
| 512³ | var#8 | 680.7 | 523.5 | +30.0% | auto |
| 768³ | var#8 | 582.4 | 470.0 | +23.9% | auto |
| 1000³ | var#38 | 375.8 | 510.1 | −26.3% | family |
| 1024³ | var#4 | 413.9 | 367.1 | +12.7% | auto |
| 1365³ | var#47 | 465.0 | 494.9 | −6.0% | family |
| 2048³ | var#43 | 801.0 | 547.2 | +46.4% | auto |
| 4096³ | var#9 | 868.5 | 667.6 | +30.1% | auto |

**Deep-dive findings:**
- **Best absolute numbers**: 4096³ var#9 = 868.5 med / 990.7 max; 2048³ var#43 = 801.0 / 940.6; 512³ var#8 = 680.7 / 692.3. These top the whole oto corpus (cf. §5.1 family-carried SS best ≈ 671 GFlops @ 4096³; auto run 868.5 @ 4096³ → +29%).
- **No single dominant knob combo** — the winner varies by shape (var#9 at 256/4096, var#8 at 512/768, var#4 at 1024, var#43 at 2048, var#38 at 1000, var#47 at 1365). Strong shape-size effect.
- **VW=2 dominates VW=1** at every size (var#42/#43/#44-ish cluster beats var#46/#47); WGM matters most at mid sizes; NLCA=3 slightly preferred at large tiles.
- **Auto beats family best at 6/8 shapes** (all except 1000³, 1365³). Family superiority there comes from wider MT/TT exploration (MT128/64 splits) that the fixed MT96x96x16/TT6x6 auto space cannot reach.
- **Best-vs-worst spread within a shape** is large (2048³: 277.7 GFlops between var#43 and var#46) — knob choice matters more than tile shape at big sizes.
- 1000³ is pathological (only 375.8 best, spread 62). Likely purely-memory-bound: no knob recovers it.

### 11.5 Why the Loop Stalled (root cause)

`run_auto` (port_tensile.py:830) iterates:
```
winners = harvest(all_analytics)      # 8 winners keyed by (dtype,shape)
new_candidates = mutate_and_feed(winners, mutation_budget)   # agent.py
if not new_candidates: stop
```
**Bug**: `mutate_and_feed` (agent.py) appends every *valid* mutant to `new_candidates` **and** calls `scheduler.append_candidates_batch` (scheduler.py:456) which **dedups by fingerprint** and may add 0. The returned list is never emptied on dedup, so `if not new_candidates` is never True ≥1 valid mutant exists — even though 0 actually enter the manifest.

Simulation over the 72 cells: harvest → 8 winners → 84 valid mutants, **52/84 fp-collide** with the existing manifest (TT=4/8, MT=64/128 variants already present as family phases). So the append is all-dedup, manifest stays at 304 (232 family + 72 auto), and each pass re-runs only the 12 failing `hs_hpa` phases while 292 skip via `identical_fp`. Loop spins until SIGINT.

### 11.6 Persistent Blocker: HS_HPA (12 phases, "0 valid solutions")

Phases `phase_hs_hpa_{Ailk,Alik}_{Bjlk,Bljk}_{256,512,1024,2048}` fail with Tensile `Your parameters resulted in 0 valid solutions` on **every** pass (48 failed records = 12 × 4 completed passes, 4th attempt in pass 5 truncated). HPA = High-Precision Accumulate formulation (prefers `_BHS`/`_BHHB` split kernels); the chosen MS=8/MR=8/MT64 variant is not assemblable on gfx90c ISA (9,0,12). Family phases for the same problems exist and pass — only the HPA path is broken.

**Correction (2026-09-19, see `potential_configs.md` §4):** `PrintSolutionRejectionReason` traced the "0 valid solutions" to stock-Tensile's non-MI assembly `GLVW==VW-or-1` generator guard (`SolutionStructs.py:4583-4596`), triggered by pv-reduction of GLVW 4→2 in `setGlobalLoadVectorWidth` (`:2010-2047`) — isa-independent, i.e. a parameterization/generator restriction, not a gfx90c HW/ISA limit. Guard-legal HS_HPA parameterizations (MT64x64x16/TT4x4/VW4/DU16; MT64x64x8/TT4x4/VW2/DU8) are admitted 1/1 and assemble for gfx90c; HS_HPA tuning resumes on them.

### 11.7 Root Causes Summary (for the port write-up)

1. **Convergence-continuation bug** (`mutate_and_feed` returns non-empty list even when 0 candidates are accepted by fp-dedup).
2. **HS_HPA blocking config** — must be de-listed or fixed before any `--auto` run can complete.
3. **`identical_fp` re-skip semantics** — every downstream pass re-failed/re-skipped the full list; a "done" marker would have let the loop exit.
4. **True 4D-volume cost**: the loop materialized no new geometry because the fixed (MT96,T T6) auto space plus family coverage left no fp-new candidates.

### 11.8 Takeaway for Next Run

- Run `--auto` with `hs_hpa` excluded (or fix its kernel split) to get a clean convergence exit instead of an interrupted 7h40m spin.
- Enlarge the auto variant space (add TT=4/8, MT=64/128, NLCA=2) to produce genuinely new candidates post-first-pass.
- Treat 1000³/1365³ as memory-bound ceilings; do not expect knob gains there.

---

*Last updated: 2026-09-15T08:20*
