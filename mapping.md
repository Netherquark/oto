# mapping.md — Shipped gfx900 footprint → native gfx90c replication contract

Status: **ground truth extracted + replication contract; oto uses this to emit native family phases.**
Date: 2026-09-13 (kernel counts re-derived live from the dat on 2026-09-25)
Sources: the shipped gfx900 footprint `TensileLibrary_*_gfx900.dat` (decoded from the installed rocblas `library/` dir — ROCm prefix per `.env`/§6), `gfx90c_common.py`, measured prior conclusions (`prior_INSIGHTS_CAVEMAN_ULTRA.md` §5.1). Kernel identity now comes from `tensile_library.py` (union of `/usr` + `/opt/rocm` prefixes; deduped canonical `Cijk_...` solution names, msgpack-length-prefixed in the dat), pinned once at `gfx90c_results/gfx900_shipped_manifest.json` after first load. The earlier 3,066 was per-file token counting; the clean per-family total below is 2,285.

## 1. What the shipped gfx900 library actually is

28 frozen family libraries (+1 lazy placeholder), **2,285 shipped kernels** (live-derived, see `expected_kernels` in the manifest), all mapped onto a
**defensive static mesh** for arbitrary problem shapes, NOT a per-shape tuning result.

| Family | dtype/op set | kernels |
|---|---|---|
| CC | complex | 64 |
| DD | double (U-tiles) | 96 |
| ZZ | small/edge | 26 |
| HH | FP16 (packed) | 223 |
| HH_HPA | FP16 HPA | 424 |
| HS_HPA | FP16 scalar-acc | 493 |
| SS | single 32-bit (big tiles, deep K) | 959 |
| **Σ** | | **2,285** |

Each family = 4 contraction patterns: `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`
(SS `Ailk_Bljk` alone: 659 kernels, 1,980 unique size-keys). Top global tiles:
`MT64x64x16` 336, `MT64x64x8` 208, `MT128x64x16` 157, `MT32x32x16` 150, SS heads
`MT128x64x16/MT64x64x16/MT128x64x8`. DD heads `MT64x64x8/MT32x32x8`; HH heads
`MT64x64x16/MT128x64x16`; HPA heads `MT64x64x16/MT64x64x8`; HS heads `MT64x64x8/MT64x64x16`.

gfx900 kernels are **not loadable on gfx90c** (arch-mismatch; ISA900 spoof-builds
mislabel every metric). Native `--arch gfx90c` is supported.

## 2. Replication contract (what oto must produce)

**Reproduce the family matrix natively; let Tensile pick native tiles per family/cell.**
Do NOT chase the 1,980-key size tables — those document the defensive mesh. Anchor the
workload cells (shapes 256³/512³/1024³/2048³ + the suite problem cells) and
emit per-family tile decks from:

1. the mapped gfx900 top-tiles above (translated, never copied: `_ISA900_` kernels are
   not runnable), and
2. the measured frozen prior winners (below) — the only datapoints
   already gfx90c-native (frozen prior conclusions, per `prior_INSIGHTS_CAVEMAN_ULTRA.md`).

The spoof floor for A/B is the **shipped footprint itself**: `--gfx900-reference`
benchmarks every shipped kernel once (ScheduleName `vega10`, at the family deck shapes
from `FAMILY_SHAPES`) into a permanent `gfx900_ref_*` run, recalled — never re-run —
by every later acceptance report. Expected coverage denominators now come from that
pinned manifest, not this (historical) table.

## 3. Native kernel levers that moved the needle (measured, frozen prior)

| Regime | Winner config (native, verified) |
|---|---|
| FP32 large square 1536–4096³ | `SB_MT96x96x16_SN_NLCA3_TT6_6_VW2_VWB2_WG16_16_1_WGM4` (~890-960; 1118.7 @1024³ w/ MT128x128x16 p27) |
| FP32 odd 768³/1000³/1365³ | `SB_MT96x96x16_AMAS3_VW2_NLCA3_TT6_6_WG16_16_1_WGM4` |
| FP32 GEMV decode M1-64 | `SB_MT8x32x32/MT16x32x16/MT32x64x32 + TT1_4/TT2_4/TT4_8 + VW1/VW2 + WG8_8_4_WGM8` |
| FP32 GEMV deeper M32/64 N=K≥2048 | candB `MT32x64x32`; **32x4096x1 +8.1/+13.6%**, **64x4096x1 +17.8/+21.3%** (harvested) |
| FP16 large square | `HB_MT128x128x16_SN_EPS0_NLCA1_PGR0_TT8_8_VW4_VWB4_WG16_16_1` (2492.1 best) |
| FP16 GEMV | `HB_MT16x64x32/SB_MT64x64x16 ... TT2_8/TT4_4`; 64x4096x4096 = 1016 |
| BF16 | `BBS_BH_MT128x64x8/MT128x128x16 ... EPS1_PGR1` (1108.5 best, single-rate) |
| FP64 | `DB_MT32x32x16_AMAS3` / `DB_MT64x64x8` (98.6 = 98% of pipe; saturated) |
| INT8 | `I8II_BH_MT128x128x16_SN_TT8_8_WGM1` (881.2 best; 1024³ INT8 = **+18.3% win** vs spoof) |
| Batched / short-K | candF regimes: 64x11008x1, 4x2048x64, 64x2048x16 (first-ever data) |
| Grid underfill fix | GSU only when grid underfills 7 CUs: 256³→GSU8, 512³→GSU2, 128x128x2048→GSU1 |
| Label-only (ignore) | `ScheduleName: "isa"` vs `"vega10"` — verdict G, no measured effect |

Ruler/floor numbers (single-rate; ceiling authority `gfx90c_theoretical_limits.md`):
FP32 1613, FP16 3226, BF16 1613, INT8 1613, FP64 101.

## 4. Enforcement (how the contract is kept)

- Family coverage = the mapped matrix; each emitted phase is native `isa`, name =
  `phase<N>_<family>_<pattern>` (or collides into existing phase labels by purpose).
- Per-cell verdict uses **throttle-adjusted median-of-seeds**, ±5% tie band.
- Peaks are never a signal; gfx900 spoof is a floor; `SPOOF floor is never re-rolled`
  (phase-1 first-ever-run-only).
- **Retire only on sampling-gated evidence** (≥2 independent runs/cell + CV gates),
  never on a single N=1 run.
- No re-sweep of already-failed cells (potential_configs verdicts carried).

## 5. Concrete next actions (registered in implementation_plan.md Steps 3-6)

1. Emit native family decks in `phases.yaml` (Step 3).
2. Deterministic `--auto` loop drives coverage + convergence (Step 4).
3. Synthesis + anti-alias + whole-library readout (Step 6).