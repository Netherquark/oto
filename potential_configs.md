# gfx90c — attempt2 Potential & Convergent-Candidate Configurations

> Role: candidate deck + search rules for the deterministic loop. Not a store of
> raw benchmark data (that's `results.md`). Prior-campaign verdicts are carried as
> the deck's seed knowledge (conclusions only — sanctioned source:
> `prior_INSIGHTS_CAVEMAN_ULTRA.md`); attempt2 runs them through the deterministic
> harvest → mutate pipeline.

## 1. What has already been tried (carried verdicts)

Candidate sweep A–G over 21 shared cells (throttle-adjusted, ±5% band, median-of-seeds)
→ **5 W / 10 T / 6 L**.

| Candidate | Result | Action for attempt2 |
|---|---|---|
| A sgemm controller sweep (p16) | 0W/3T/0L (2048³ +0.3..+5.6) | keep 2048³ as deck seed; do NOT re-sweep |
| A hgemm (p17) | 0W/0T/3L (−8..−9%) | drop |
| B LLM-decode GEMV deeper (p18) | **2W/3T/0L**: 32x4096x1 +13.6%, 64x4096x1 +21.3% | **harvest as incumbent** (native GPUs) |
| C asymmetric/odd (p20/p25) | **CRASHED every run** (`AssertSizeMultiple: [1]`) | fix `[{}]` applied; scoped re-test `--phases 20 25` |
| D occupancy/LDS (p19) | 512/1024³ L (−8.6/−19.7%); **2048³ W +14.1/+20.1%** | harvest 2048³; kill sweep path |
| E bf16 (p22) | 0W/1T/1L (−13.6% @1024³; +2.4% @2048³ T) | keep 2048³ seed; don't chase bf16 |
| E fp64 (p23) | 0W/1T/2L (ties +0.1%; pipe-saturated) | drop new sweeps; fp64 is done at 98% |
| E int8 (p24) | **1W/1T/0L**: 1024³ **+18.3% W** | **harvest**; strongest win |
| F batched/short-K (p21) | 3 genuinely-new cells (64x11008x1, 4x2048x64, 64x2048x16) | keep cells, harvest best |
| G schedule vars | label-only, no effect | ignore |

**Other carried facts:**
- Only 6 genuinely-new problem cells were ever produced. attempt2's main axis is
  **coverage** of the 28-family footprint (see `mapping.md`).
- FP64 at 98% of a 101 GFlops pipe → no headroom; do not spend GPU on it except to
  confirm port-level correctness.
- Best measured per datatype (carried ceilings, `results.md` §2): FP32
  1118.7@1024³, FP16 2492.1@4096³, BF16 1108.5@2048³, INT8 881.2@2048³, FP64
  98.6@1024³.
- Envelope: ±23–31% raw ALU swing; ties at ±5% = parity; winner instability 77%.

## 2. Deterministic candidate rules (the convergence core)

- **N4/H7 (kept):** mutate the current per-cell winner by **≤2 knobs** (neighbours),
  never resweep a wide grid; drop any fingerprint already benchmarked.
- **N8 (kept):** winner statistic = median-of-seeds; max is reference-only.
- **NP (attempt2, no consultation):** knob pool is fixed and gfx90c-legal:
  `MacroTile`, `ThreadTile`, `WorkGroup`, `WorkGroupMapping`, `DepthU`,
  `GlobalSplitU`, `PrefetchGlobalRead`, `PrefetchLocalRead`, `VectorWidth`,
  `NLCA`, `EPS`, `Stages`. No matrix instructions, no `SIA>1`, no Fp16AltImpl.
- Mutation is then **deterministic + gated**: each candidate must keep a valid
  (occupancy/LDS) footprint (that is what killed candD forks) — the validator checks
  LDS fit on 64 KB/CU and 7-CU occupancy ≥ some floor, config-valid (no
  `AssertSizeMultiple: [1]` style), fp unique (no re-run).
- **Budget:** configurable wall-time/GPU-minutes + finite per-phase timeout default;
  the loop stalls → the phase gets one interactive skip/kill.

## 3. Search spending rules

- Coverage (new family×pattern×shape cells) has priority; then mutate the newly
  discovered winners.
- A config is only worth GPU time if ALL hold: median-of-seeds with NumBenchmarks ≥ 3;
  a ruler/reference shape repeats every run (throttle control); no known-crash config;
  formulation is "mutate the per-cell winner", not "resweep a grid over already-tuned
  shapes".
- Do NOT re-sweep what already failed (carried verdicts; `results.md` §5).
- Missing rulers stay missing, never inferred (FP16-DDR/BF16-DDR remain absent by
  design until a real BF16/FP16 GEMV control cell runs).
- The manual-LLM contingency is add-only, user-invoked, ≤5 candidates dumped into
  `phases.yaml` — same pipeline, never in the loop.

## 4. Decisions log (attempt2)

- 2026-09-13: attempt2 = deterministic convergence; no LLM in loop; manual-LLM
  add-only worst case. Driver per `implementation_plan.md` §The Driver Architecture.
  Coverage-first per Step 3.
- 2026-09-13: acceptance narrowed to TWO measures — (1) beat the gfx900-spoof floor
  across the whole shipped suite; (2) approach the per-family ceilings of
  `gfx90c_theoretical_limits.md` §5 (measured utilization logged per
  (family, bound_class)). Occupancy (GSU/WGM/MT/TT right-sizing) is the first-class
  objective, not a constraint (T9).
- Carry-over: candidate C 20/25 re-test remains scheduled (`--phases 20 25`).

## 5. Next-round candidate deck

Working area the deterministic loop appends to (`phases.yaml` mirror). Entries are
`(family, cell / shape, incumbent config knobs, best median GFlops, % of family
ceiling, next mutation)`. Data source: `run_20260913_215546` (93 CSVs / 101 cells).

### 5.1 Incumbents by family (median-of-seeds, per winning cell)

Winner statistic per N8; ceilings per `gfx90c_theoretical_limits.md`. Data:
`gfx90c_runs/run_20260913_215546` (93 CSVs → 101 cells, 66 RED at <50% ceiling).

> **ss/1024³ stale-CSV caveat:** the 1024³ CSV under
> `phase_phase_ss_Ailk_Bljk_1024x1024x1024` was produced by a kernel
> `Cijk_Ailk_Bljk_SB_MT96x96x16_SN_K1` (MT96) while the archived config in that
> run dir is MT64/TT4/NLCA3 — the CSV is stale from an earlier overwritten config,
> and the same dir logs `Actual Solutions: 0 / 1 after SolutionStructs`. The
> 397.2 media for ss/1024³ therefore belongs to the **MT96** variant, not the MT64
> "seed"; treat the MT64 seed as un-runnable under NLCA3 (see §5.2/§5.3 for the
> Tensile-divisibility root cause and the NLCA fix).

| family | shape | best median GFlops | %ceil | winning phase |
|---|---|---|---|---|
| cc | 256³ | 230.4 | 20.6 | `phase_phase_cc_Ailk_Bjlk_256x256x256` |
| cc | 512³ | 175.9 | 15.7 | `phase_phase_cc_Ailk_Bljk_512x512x512` |
| cc | 1024³ | 157.4 | 14.1 | `phase_phase_cc_Ailk_Bjlk_1024x1024x1024` |
| cc | 2048³ | 281.3 | 25.1 | `phase_phase_cc_Ailk_Bjlk_2048x2048x2048` |
| dd | 256³ | 76.2 | 77.3 | `phase_phase_dd_Ailk_Bjlk_256x256x256` |
| dd | 512³ | 55.1 | 55.9 | `phase_phase_dd_Ailk_Bjlk_512x512x512` |
| dd | 1024³ | 77.5 | 78.6 | `phase_phase_dd_Ailk_Bjlk_1024_depthu4` |
| dd | 2048³ | 92.2 | 93.5 | `phase_phase_dd_Alik_Bjlk_2048x2048x2048` |
| hh | 256³ | 748.2 | 30.4 | `phase_phase_hh_Ailk_Bjlk_256x256x256` |
| hh | 512³ | 1127.8 | 45.8 | `phase_phase_hh_Ailk_Bjlk_512x512x512` |
| hh | 1024³ | 847.2 | 34.4 | `phase_phase_hh_Alik_Bljk_1024x1024x1024` |
| hh | 2048³ | 853.2 | 34.7 | `phase_phase_hh_Ailk_Bljk_2048x2048x2048` |
| hh_hpa | 256³ | 576.9 | 51.6 | `phase_phase_hh_hpa_Ailk_Bjlk_256x256x256` |
| hh_hpa | 512³ | 1183.2 | 105.8 | `phase_phase_hh_hpa_Ailk_Bljk_512x512x512` |
| hh_hpa | 1024³ | 866.3 | 77.4 | `phase_phase_hh_hpa_Alik_Bjlk_1024x1024x1024` |
| hh_hpa | 2048³ | 896.3 | 80.1 | `phase_phase_hh_hpa_Ailk_Bjlk_2048x2048x2048` |
| hs_hpa | 256³ | 603.7 | 54.0 | `phase_phase_hs_hpa_Alik_Bljk_256x256x256` |
| hs_hpa | 512³ | 781.1 | 69.8 | `phase_phase_hs_hpa_Alik_Bljk_512x512x512` |
| hs_hpa | 1024³ | 511.4 | 45.7 | `phase_phase_hs_hpa_Alik_Bljk_1024x1024x1024` |
| hs_hpa | 2048³ | 517.3 | 46.2 | `phase_phase_hs_hpa_Alik_Bljk_2048x2048x2048` |
| ss | 256³ | 415.0 | 37.1 | `phase_phase_ss_Ailk_Bjlk_256x256x256` |
| ss | 512³ | 530.4 | 47.4 | `phase_phase_ss_Ailk_Bljk_512x512x512` |
| ss | 1024³ | 397.2 | 35.5 | `phase_phase_ss_Ailk_Bljk_1024x1024x1024` |
| ss | 2048³ | 890.8 | 79.6 | `phase_phase_ss_Ailk_Bjlk_2048x2048x2048` |
| zz | (all 26) | — | — | no CSVs yet (see §5.3) |
| auto (s) | 1024³ | 421.6 | 37.7 | `phase_phase_auto_0_Unknown_1024x1024x1024_9` |
| auto (s) | 2048³ | — | — | auto deck is all-1024³; SS 2048³ covered by `ss_Ailk_Bjlk` |
| 1 (s) | 1024³ | 460.9 | — | `phase_phase_1` |
| 1 (s) | 2048³ | 633.9 | — | `phase_phase_1` |
| 1 (s) | 4096³ | 665.5 | — | `phase_phase_1` |
| 20 (d) | 1000³ | 520.0 | — | `phase_phase_20` |
| 25 (d) | 1000³ | 505.9 | — | `phase_phase_25` |
| 31 (s) | 4096³ | 655.5 | — | `phase_phase_31` |

### 5.2 Auto-mutation results (SS deck, generated deck headings)

Only **9/30** generated auto configs returned CSVs (idx 4,6,8,9,38,42,43,46,47);
idx **10–13** were generated but never benchmarked and the remaining 21 produced no
CSVs. **Root cause now confirmed (2026-09-14):** the 21 un-CSVed auto configs were
rejected inside Tensile's `SolutionStructs.setGlobalLoadTileDimClassic` — NLCA / VW /
DepthU divisibility violations (`Actual Solutions: 0 / 1 after SolutionStructs`) — so
**they are NOT re-runnable as-is** and must not be spent on GPU time. The validator
(`CandidateGenerator._validate_tensile_loads`) now enforces these checks at mutation
time. All benchmarked ones on 1024³:

| config | MT | TT | NLCA | VW | WGM | med GFlops | max GFlops | vs seed |
|---|---|---|---|---|---|---|---|---|
| auto_9 | 96x96 | 6x6 | 3 | 2 | 1 | 421.6 | 440.6 | **+6.1%** (seed 397.2) |
| auto_8 | 96x96 | 6x6 | 3 | 2 | 8 | 408.5 | 485.4 | +2.8% |
| auto_38 | 96x96 | 6x6 | 1 | 1 | 4 | 404.9 | **607.8** | +1.9% (max is a single volatile seed) |
| auto_42 | 96x96 | 6x6 | 1 | 2 | 8 | 400.7 | 440.3 | +0.9% |
| auto_43 | 96x96 | 6x6 | 1 | 2 | 1 | 398.7 | 496.9 | +0.4% |
| auto_4 | 96x96 | 6x6 | 1 | 2 | 4 | 397.6 | 467.0 | +0.1% |
| ss seed (Ailk_Bljk) | 64x64 | 4x4 | 3 | 2 | 4 | 397.2 | 498.3 | — (MT96 kernel; see §5.1 caveat) |
| auto_6 | 96x96 | 6x6 | 3 | 1 | 4 | 379.2 | 492.5 | −4.5% |
| auto_46 | 96x96 | 6x6 | 3 | 1 | 8 | 373.8 | 438.1 | −5.9% |
| auto_47 | 96x96 | 6x6 | 3 | 1 | 1 | 364.5 | 523.7 | −8.2% |
| auto_7 (no CSV) | 96x96 | 6x6 | 3 | 4 | 4 | — | — | rejected (SolutionStructs) |

`auto_9` is the first auto-phase config to beat the carried SS seed → **harvest**
as the new SS 1024³ incumbent. 2048³ SS: `ss_Ailk_Bjlk` (890.8, 79.6% ceil) stays.
**Mutation-analysis conclusion (idx 9 best):** the seed (MT64/TT4/NLCA3) is a **local
optimum at ~397**; the NLCA=3 knob is Tensile-legal only on MT96/TT6+VW2 (`Ailk_Bjlk`)
and is otherwise the main rejection source — structural candidates below therefore fix
NLCA to auto (1) unless it is the proven 421.6 combo.

### 5.3 Next-round deck (mutate incumbent ≤2 knobs, gfx90c-legal pool)

Proposed candidates in priority order (spend rules §3: coverage first, then mutate):

1. **ZZ coverage (pending user launch)** — 32 published targets (16 cells × MT/TT
   variants 32x32x16/2x2 and 64x64x16/4x4), **NLCA fixed (was 3, now removed→auto)**,
   all resolve via `--family ZZ --dry-run`. User launches on own time.
2. **Auto 21 un-CSVed configs — REJECTED, DO NOT RE-RUN** (corrected 2026-09-14):
   these are `Actual Solutions: 0 / 1 after SolutionStructs` divisibility rejects
   (NLCA/VW/DepthU), not launch failures. Re-running them as-is wastes GPU time;
   they must first be re-emitted through the new `_validate_tensile_loads` gate
   (e.g. NLCA 3→1, VW 4→2 like auto_7). The 21 are idx
   10,11,12,13,28,29,32,33,36,37,39,40,41,44,45,48,49 and timeouts.
3. **Structural candidates (SS/cc/hh)** — NLCA fixed to auto except where proven:
   - `MT128x128x16 / TT8x8` (fam2 root cause was NLCA=3 on 4 loads → NLCA auto,
     NumLoads=4, 2048 extra register headroom) — candidates for ss 1024³, cc, hh.
   - `MT64x64x16 / TT4x8` (asymmetric TT: 4x8 lifts B-side occupancy without the
     NLCA3 trap of TT4x4; glvw=2 keeps divisibility).
   - `GlobalSplitU 2/4` variants of the per-cell winners (occupancy first-class, T9).
   - `NLCA auto` everywhere except the proven `Ailk_Bjlk`/MT96/TT6/VW2=3 combo.
4. **cc 1024³ (14.1%) & 512³ (15.7%)** — worst headroom; mutate
   MT64x64/TT4x4/WGM4 seed: `DepthU 8→16`, `WorkGroup [16,16,1]→[8,8,1]` and
   GSU 2/4 variants (structural deck above).
5. **ss 1024³** — `auto_9` (MT96x96/TT6x6/NLCA3/VW2/WGM1, 421.6) is the new seed;
   mutate WGM {1,4,8} × DepthU {16,32} only. Note `auto_38`'s 607.8 is a single
   volatile seed, NOT the median (404.9) — do not chase max.
6. **hh 1024³ (34.4%) & 2048³ (34.7%)** — mutate MT64x64/TT4x4 seed: MT
   {64,128}×{64,128}/TT8x8, NLCA auto (1), WGM 4→8 — structural deck. hh_hpa 512³
   already 105.8% ceil.
7. **hs_hpa 1024³/2048³ (45%)** — mutate GG group size / WGM; skip 512³ (69.8%).
8. **dd — closed**: 93.5% @2048³, pipe-saturated (E verdict); no GPU spend.

**Convergence proposal (LLM-advisor, verified ceilings):**

| family | today (best cell) | target | how |
|---|---|---|---|
| hh / hh_hpa | 34–46% (1127.8) | **50–57%** | hpa 2:4 + MT128/TT8 + GSU4 structural deck; hh_hpa 512³ already 105.8% |
| cc | 15–25% | **≤29%** then stop | cc 512³/1024³ are RED headroom; structural candidates + GSU |
| ss | 35–80% | **~54% @1024³** stable | chase auto_9 mutation cluster (WGM/DepthU), NOT max |
| dd | 93.5% | near-saturated **99%** | no GPU spend (E) |
| zz | no data | cover 26 cells first | user-launched ZZ run (NLCA fixed) |

Any new phase must be `validate_config`-clean (occupancy/LDS) **and** pass
`_validate_tensile_loads` (Tensile divisibility — new requirement 2026-09-14) and
the `<host>/<knob>` uniqueness gate (no re-run of a fingerprint already benchmarked).
All 230 phases.yaml contraction entries currently pass both gates (48 invalid
entries were fixed in place: NLCA 3→1 ×46, DepthU 4→16 ×2; backup
`archive/phases_20260914_prefix.yaml`).