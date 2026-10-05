# gfx90c — oto Implementation Plan (One-Shot Deterministic Convergence)

> Status: **APPROVED-IN-PRINCIPLE**. Native port mechanics are proven (frozen
> baseline: parity at 0/11/0 same-run; the gap is coverage + beating
> the spoof floor). oto contract: **beat the gfx900 spoof baseline across the
> entire shipped kernel suite** AND approach the gfx90c theoretical limit as closely
> as possible (limit authority = `gfx90c_theoretical_limits.md`, cross-checked
> against rocminfo + first-party sources). Ruthless simplicity; deterministic; NO LLM
> in the loop. THIS FILE IS SELF-CONTAINED — it carries the driver architecture and
> the triaged-fix disposition. Read it top-to-bottom before implementing.

## Objective

Produce native `gfx90c` Tensile libraries covering the shipped 28-family × 4-pattern
footprint (2,285 distinct shipped gfx900 kernels = 7 dtype/op families × 4 contraction
patterns; the earlier 3,066 was per-file token counting, see `mapping.md`), converging
per-cell so that each cell's ruler-adjusted median-of-seeds
winner **beats the gfx900-spoof floor** (ties at ±5% = parity, and parity alone is not
the win the campaign is here for). ±5% is the standing success bar, but it is
narrower than the measured repeat noise (CV p90 27.8%, `results.md` §12.3), so a
±5% "parity" is not evidence of indistinguishability — grade with `ab_audit.py`
(±27.8%) when the claim matters. and lands as close to the `gfx90c_theoretical_limits.md`
ceiling for its (family, bound_class) as the machine will give. The whole campaign is
driven by `port_tensile.py --auto` (deterministic harvest → mutate ≤2 knobs → re-run).

Stated goal (from `tensiles_in_system_rocm.txt`): replicate and produce a
`tensilelibrary` that performs all of the shipped functions for gfx90c, performing
**better** than gfx900 spoofing. No more, no less.

## Core Strategy (one-shot deterministic convergence)

```
shipped `gfx900` footprint (28 families, 4 patterns = 418 phases:
SS 105 · DD 44 · HH 40 · HH_HPA 20 · HS_HPA 20 · CC 32 · ZZ 40 · legacy auto 117
— re-derived 2026-09-27: 410 + 8 legal ZZ replacements after the occupancy gate,
see `changelog.md`)
    ↓ translate decks (mapping.md) — never copy ISA900 kernels
native gfx90c family phases
    ↓ correctness (compiler + client + anti-alias)
HW benchmark (median-of-seeds, ruler-adjusted)
    ↓
deterministic evaluate → harvest wins / mutate ≤2 knobs / tie
    ↓
convergence (no RED cells) → synthesis → acceptance readout
```

## AI Must Not Decide

`gfx90c identity / ISA legality / AsmCaps / compiler flags / runtime support /
correctness / measurement / accepted performance` — including in the manual-LLM
contingency. The model only proposes candidate *parameter vectors*; Tensile generates,
the compiler validates, the hardware decides, the DB remembers.

## Correctness Gate

Always: generate → correctness → benchmark. Never: benchmark → fast → maybe correct.
Wrong kernel = failed candidate. The validator must reject known-invalid configs
(no `AssertSizeMultiple: [1]`, no `SIA>1`, no Fp16AltImpl, LDS ≤ 64 KB/CU).

## Reward Hacking

Independent benchmark + fresh inputs + correctness validation + repeat runs + guard
checks + dtype-specific tolerance. Evaluator stays outside model control. No
max-of-seeds; median-of-seeds is the statistic.

## Manual-LLM Contingency

User-invoked, add-only, worst case only. A single canned prompt producing ≤5 candidate
recipe mutations, dumped into `phases.yaml`, flows through the same deterministic pipeline.
Never an in-loop consultation.

## Important Details (verified current state)

### A. Frozen baseline (conclusions sourced from `prior_INSIGHTS_CAVEMAN_ULTRA.md`)
- Port mechanics **DONE**: pristine Tensile + minimal in-tree gfx90c support
  (3 bookkeeping entries in `Tensile/{Common,AsmCaps}.py`); Phase-0 gates 10/10
  [OK]; anti-alias 0 gfx900 leak; synthesis PASS.
- Performance = **parity, not wins** on the only same-run pair (0 / 11 / 0 at ±5%).
  Candidate suite A–G gave **5W/10T/6L** over 21 shared cells.
- 6 genuinely-new problem cells were produced. Best measurements: FP32 1118.7 @1024³,
  FP16 2492.1 @4096³, BF16 1108.5 @2048³, FP64 98.6 @1024³, INT8 881.2 @2048³.

### B. The replicated footprint (mapping contract, see `mapping.md`)
28 frozen families = 7 dtype/op sets × 4 contraction patterns:
`{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}` × `{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`
= **2,285 distinct shipped kernels** (459+ distinct size-keys; the old 3,066 was
per-file token counting — see `mapping.md`). No gfx90c library ships anywhere today.
Reproduce the family matrix natively; per-family tile decks come from the mapped
gfx900 top-tiles + the measured prior winners (frozen conclusions); do NOT chase the
1,980-key size tables (defensive mesh, not a tuning result).

### C. Theoretical limits (authority: `gfx90c_theoretical_limits.md`)
Per-family FMA roofs @1800 MHz: SS 1613, DD 101, ZZ 1613, CC 101, HH 3226,
HH_HPA/HS_HPA 1613; BF16 single-rate 1613 (no `v_pk_fma_bf16`); INT8 1613 upper
bound only (no dot → ~881 realistic). DDR roofline 42 GB/s (measured-achievable).
Realistic ceilings: SS ~1119 (69%), DD ~98.6 (98%), HH ~2461 (77%), BF16 ~1109 (69%),
INT8 ~881 (55%); ZZ/CC/HH_HPA/HS_HPA derived-analytical ~1119/98/1119/1119. Every
convergence verdict compares against these, throttled+median-of-seeds.

### D. Measurement discipline (carried, fixed, non-negotiable)
- Winner = **median-of-seeds** (NumBenchmarks ≥3); max = reference only.
- Comparisons = **throttle-ADJUSTED** per (datatype, bound_class) ruler; missing
  controls reported, never inferred (`gfx90c_common.py`).
- Envelope: raw cross-run ±23–31% ALU / ±6–19% DDR. Ties at ±5% = parity.
- Retirement is the evidence-gated single Tier-2 path
  (`policy.check_retirement_eligibility`); the spoof/peak floor is never a
  retirement signal.
- Telemetry = sysfs, header-in-CSV; sclk ruler valid only with ≥10 samples and
  median busy>0.

### E. Hazards vs objectives — the user-corrected framing
- **A finite per-phase `--phase-timeout` default ships as generic runaway protection**
  (robustness against an unexpected oversized/hung cell — resilience, not a
  size-specific special case). The protected contract is "port the shipped kernels",
  and no out-of-footprint cells are scheduled.
- **`CpuThreads: 1` is NOT dogma — it is a toolchain problem to SOLVE.** The
  `unknown resource type` child kills are a joblib/loky-vs-Python-3.14 incompatibility,
  and the generator shares mutable `globalParameters`. oto **fixes** the
  parallelism properly (default `CpuThreads: min(os.cpu_count(), 16)`, shipped in
  changelog "[Multi-Threaded Compilation] 2026-09-13"); the pre-fix sequential
  `CpuThreads: 1` narrower is retired, retained only as changelog history.
- **CU occupancy ≤3 is the performance target, not a hazard.** Low achieved occupancy
  = hardware under-utilization = the very headroom "approach the theoretical limit"
  exists to claim. Occupancy is capped by VGPR pressure + grid underfill on the 7-CU
  part (see `gfx90c_theoretical_limits.md` §7); oto's knob budget treats
  right-sized `GSU`/`WGM`/`MT`/`TT` as a FIRST-CLASS objective with measured
  utilization as the score, not an accepted constraint.
- Sustained 2048³-style benchmark marathons on this APU can wedge it (HW-exception
  GPU Hang observed). Rule: detached+killable GPU phases + cooldowns. Runtime
  guardrail, not a cell ban.

## Work State

### Completed

#### Corpus consolidation + locked floor (2026-10-03)
- Floor **locked, not re-measured**: `gfx900_ref_locked_52149f315d`, built by
  pooling all 3802 CSVs / 2194 phases from the 3-run chain. `reference_chain()`
  resolves to exactly this one run. The id is `sha256(chain)[:10]`, so re-running
  is a fixpoint rather than minting a new floor each time.
- Deck consolidated to **29 phases covering 38/38 target cells**, all multi-shape
  (4–8 shapes each), every entry a verbatim archived phase, every cell's best
  measured solution retained including the six losses. 28 illegal phases dropped.
- `consolidate.py` (mine / stage / `--commit`) + `ab_audit.py` formalised on top
  of the canonical loaders; `tests/test_consolidate.py` + `tests/test_ab_audit.py`
  = 32 tests passing.
- Fixed four correctness defects that were silently shaping results: missing
  global-load byte cap in the CPU gate (`ZZ` byte width 8 → 16), per-phase floor
  selection biasing the floor *down* on 17/38 cells, non-idempotent floor id and
  DB insert, and selection reading its own output as its candidate pool.
- `run_20261002_021805` (1168 single-shape, 0 multi-shape) archived out of the
  live loader path; 25 empty phantom run dirs moved aside. No data deleted;
  pre-consolidation state backed up with checksums under
  `archive/gfx90c_results/pre_consolidation_oct3/`.
- Integration verified end-to-end and **read-only**: `ab_audit.audit()` →
  `AcceptanceReporter.generate_acceptance_report()` produces a report against the
  locked floor with no change to registry rows or run directories.

### Next
- User-run TTY validation of the 29-phase deck. GPU work is out of scope for the
  consolidation session.
- Resolved: the ~2× invocation-form swing (658.2 multi-shape vs 333.0
  single-shape, identical config) was verified as a **real** measurement, not an
  artifact — same kernel (2 of 3 solution sets byte-identical), identical
  leading dimensions, and clock ruled out at 4–8%. It is now handled rather than
  open: grading never crosses invocation form or Tensile generator
  (`form_mismatch` / `generator_mismatch`), and the tie band is derived from
  measured repeat spread (±27.8%) instead of the unsupportable ±5%. Under that
  band the A/B reads **8 WIN / 30 TIE / 0 LOSS**, so no verdict depends on it.
- Instrumentation gap **closed and measured** (2026-10-05 native trial,
  `run_20261005_170141`): Tensile's own CSVs carry no telemetry
  (`WinnerFreq`/`Power`/`Temperature` are 0 in all 8113 files), so clocks live
  only in per-run `logs/telemetry.csv`. `telemetry.py` samples at 10 Hz with a
  **`phase_id`** column (not `phase`), and the trial confirmed it end to end:
  1,916 of 1,950 rows phase-tagged, and the phase now resolves to a real clock
  base of **1787 MHz @ 76 °C (max 82 °C)**.
- **New defect found by that trial: `gpu_busy_percent` cannot gate telemetry.**
  Requiring `busy > 50%` kept 1 of 1,916 phase-tagged samples, so cheap phases
  silently reported as unmeasured. amdgpu reports 3–8% for short/small kernels;
  `power_uw` does not separate idle from loaded either (idle median 20 W vs
  clocked 23 W, idle p95 28 W). `sclk` is the discriminator that works, and
  `SCLK_MIN_HZ` already excludes the 400 MHz idle floor. The gate is now off by
  default (`TELEMETRY_REQUIRE_BUSY = False`), kept for reporting only. Measured
  corpus impact: 53,860 → 93,427 usable samples, phase coverage 92.4% → 92.3%
  (rate unchanged), so existing clock-adjusted verdicts are not overturned.
- **Still open, and now the one thing the instrumentation was built for:** the
  form-vs-thermal question needs the *same* kernel in *both* forms on the *same*
  cell, which is exactly what the certainty tiers refuse to grade. A single
  cheap phase cannot answer it; it needs a deliberately paired run.

### Ecosystem consolidated: single `changelog.md`, `gfx90c_theoretical_limits.md`
  added, superseded MDs removed, prior conclusions held only in
  `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.
- Full driver + 7 module suite implemented, import-clean, `--help` passes.
- Valid Tensile YAML generator (`_write_phase_config`) emits `GlobalParameters` +
  `BenchmarkProblems` schema; phase 20 benchmarked successfully producing
  `2_BenchmarkData/Cijk_Ailk_Bjlk_SB_00.csv` (1 CSV confirmed, run_20260913_144805).
- **Ctrl+C signal handler fixed (2026-09-13):** `_signal_handler` now calls
  `sys.exit(130)` after killing the child process group, so Ctrl+C actually
  terminates the driver instead of just setting a flag. Run status is marked
  `interrupted` in registry before exit.
- **Stale run cleanup (2026-09-13):** `registry.cleanup_stale_runs()` added and
  called on `TensileDriver.__init__`. 3 orphaned `status=started` runs (from
  prior session crashes before graceful shutdown) auto-corrected to `interrupted`.
- **Run status semantics fixed:** `run_phases` marks interrupted runs as
  `interrupted`, not `completed`.
- **ROCm toolchain environment:** the HIP `version` file symlink under the ROCm
  prefix (prefix via `.env`/§6) is present;
  HipClangVersion parses to `6.4.43484` cleanly. The `ValueError: invalid literal`
  in runs 143115–144714 was a pre-symlink timing issue, not a code bug; resolved.
### Technical findings (2026-09-19)

- **HS_HPA rejection root-caused.** Guard trace (`PrintSolutionRejectionReason`) +
  source audit (`potential_configs.md` §4): the rejection is stock-Tensile's non-MI
  assembly `GLVW==VW-or-1` generator guard (`SolutionStructs.py:4583-4596`),
  triggered by the pv-reduction in `setGlobalLoadVectorWidth` (`:2010-2047`) —
  isa-independent, not a gfx90c HW/ISA limit, not an assembler failure.
  Guard-legal HS_HPA parameterizations (MT64x64x16/TT4x4/VW4; MT64x64x8/TT4x4/VW2)
  are admitted 1/1 and assemble for gfx90c. HS_HPA tuning resumes on them.
- **Scheduler mirror gap — FIXED (2026-09-19):** `_validate_tensile_loads` now models
  the `GLVW==VW-or-1` predicate (scheduler.py `_validate_tensile_loads`), which the
  64x64x8 deck previously violated; 6 unit tests + 410/410 manifest sweep pass.

---

## The Driver Architecture

### Stage 1 — Manifest & Phase Execution (port_tensile.py core)
**Scope:** Read phases.yaml manifest, execute each phase via Tensile CLI, collect outputs.
**Key files:** phases.yaml (data-only manifest), TensileCreateLibrary/TensileBenchmark CLI.
**Mechanics:** For each manifest row, shell out to Tensile with dtype/shapes/ScheduleName/NumBenchmarks; collect 2_BenchmarkData/*.csv, library, telemetry; persist `json.dumps` payloads via SQLite `records` INSERT (knowledge_base.md §10).

### Stage 2 — Candidate Generation (scheduler.py + agent.py)
**Scope:** Emit candidate configs for benchmarking; occupancy-aware GSU/WGM/MT/TT sizing.
**Key files:** potential_configs.md (candidate deck), mapping.md (family decks).
**Mechanics:** From mapping.md family decks + harvested winners, mutate by ≤2 knobs (neighbour search); validate LDS fit on 64KB/CU, 7-CU occupancy ≥ floor, config-valid (no AssertSizeMultiple: [1]), fp unique.

### Stage 3 — Benchmark Execution (Tensile CLI via port_tensile.py)
**Scope:** Run TensileBenchmark for each phase; detached+killable GPU processes.
**Key files:** TensileBenchmark client, configs/phaseN_*.yaml.
**Mechanics:** Setsid process groups; 's' kills current phase, 'q' quits; Ctrl+C kills in-flight benchmark group; EXIT trap stops telemetry idempotently; finite `--phase-timeout` default.

### Stage 4 — Adaptive Repeat / Convergence (stability gating & retirement)
**Scope:** Always-on stability/retirement engine; median-of-seeds aggregation; adaptive repeat; retirement gating.
**Key files:** Suite v7 PHASE 26 block, PHASE 29 N8 median aggregation.
**Mechanics:**
- Per-cell aggregate: median-of-seeds (best-of-cell median is the winner metric;
  spread=(max−med)/med reported)
- Stability gate: CV ≤ 15% per cell (enforced in `agent.converged()`); the former
  `should_repeat`/`classify_stability` matrix helpers were removed 2026-09-25
- Tie band: ±5% (parity)
- Retirement: ≥2 independent runs/cell gating via `policy.check_retirement_eligibility`
  (single Tier-2 path); append action=retire records (append-only)

### Stage 5 — Analytics & Append-Only Registry
**Scope:** APPEND-ONLY data registry; per-cell analytics; native-vs-spoof deltas; feed seeds to Stage 2, verdicts to Stage 6/7.
**Key files:** Suite v7 PHASE 29 block, gfx90c_common.py (PEAK_GFLOPS), gfx90c_theoretical_limits.md (§5 ceilings).
**Mechanics:**
- Load raw records from 2_BenchmarkData/*.csv via analytics.py/registry
- Per-cell analytics: winner via N8 median-of-seeds, spread ratio, CV, % of family-realistic ceiling (with decode DDR exemption), and cell-status classification (RED = missing contract cell, ORANGE = measured <50% ceiling, GREEN = at/above)
- Native-vs-spoof per-cell deltas: spoof arm = recalled `gfx900_ref_*` chain
  (cross-run, never re-run; `--resume` continuations fold in); withhold when no reference floor
- Append-only DB: sqlite3 `records` INSERT of `json.dumps` payloads; rows never edited/deleted
- Feed seeds to Stage 2, verdicts to Stage 6/7

### Stage 6 — Synthesis / Build (final HIP library)
**Scope:** Build final HIP library from certified winners; anti-alias enforcement; regression gate.
**Key files:** Suite v7 PHASE 28 block, TensileCreateLibrary --merge-files.
**Mechanics:**
- Query Stage-5 certified winners from DB (median-of-seeds, ruler-adjusted)
- Group by 7 dtype/op × 4 contraction patterns → emit per-op 3_LibraryLogic/gfx90c_<Op>.yaml
- Schema-validate: len(data)>=9, fields per LibraryIO.py:232-249
- TensileCreateLibrary --architecture=gfx90c --merge-files → FINAL_LIB_DIR
- Anti-alias enforcement: scan every emitted/merged YAML + artifact for gfx900/vega10 tokens; reject build on ANY hit
- Regression gate: count check vs the pinned shipped-dat manifest (`gfx90c_results/gfx900_shipped_manifest.json`, 2,285 kernels re-derived 2026-09-25); FAIL+DB row on mismatch
- FLAG: gate deferred — build must consume only certified winners, never blind-union

### Stage 7 — Acceptance A/B & Final Report
**Scope:** Per-cell native-vs-spoof A/B vs the recalled gfx900 floor; final per-family acceptance report.
**Key files:** `tensile_library.py` (dat parse + manifest + `reference_chain`), `_compute_ab_verdicts`, report.py.
**Mechanics:**
- Floor = dedicated `gfx900_ref_*` chain (ScheduleName "vega10"); `--gfx900-reference
  --resume` continues it, retrying failed phases once and reusing decided base phases
- Per-cell verdict = best-of-cell median per arm on `(family, dtype, shape)` (`cell_key`);
  delta_pct=(nat−spoof)/spoof; |Δ|≤5% TIE=parity
- Throttle variance ruled out via spread_ratio=(max−med)/med
- Cross-run pairs withheld; pairs split across base/resume are reconciled via the chain
- Acceptance REPORT: per-family coverage vs the pinned shipped-dat manifest (2,285 kernels); per-cell native-vs-spoof WIN/TIE/LOSS vs the **recalled gfx900 reference floor** (`gfx900_ref_*`, via `tensile_library.py` + `_compute_ab_verdicts`); %-of-§5-ceiling per cell; RED (missing) / ORANGE (<50% ceiling) cell lists; overall PASS/FAIL

### Stage Flow & Convergence Loops (ASCII Flowchart)

```
                    ┌─────────────────────────────────────┐
                    │         START: port_tensile.py        │
                    │         (read phases.yaml)            │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        STAGE 1: Manifest & Phase Execution          │
│  For each phase in manifest:                                          │
│    → Shell out to Tensile CLI (dtype/shapes/ScheduleName/NumBench)  │
│    → Collect 2_BenchmarkData/*.csv, library, telemetry              │
│    → Persist records (json.dumps → sqlite3 INSERT)                   │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      STAGE 2: Candidate Generation                   │
│  From mapping.md family decks + harvested winners:                  │
│    → Mutate by ≤2 knobs (neighbour search)                           │
│    → Validate: LDS≤64KB/CU, occupancy≥floor, config-valid, fp-unique│
│    → Emit candidate configs to phases.yaml                            │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     STAGE 3: Benchmark Execution                     │
│  For each candidate config:                                           │
│    → Run TensileBenchmark (detached+killable GPU processes)         │
│    → 's' kills current phase, 'q' quits, Ctrl+C kills in-flight     │
│    → Finite --phase-timeout default                                 │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STAGE 4: Adaptive Repeat / Convergence                   │
│  Per-cell analysis:                                                  │
│    → N8 median-of-seeds aggregation                                  │
│    → Stability matrix: approved/needs_repeat/needs_super_sample/tie │
│    → Selective repeat (CV>15% or top-2 gap<3% → double NumBench)    │
│    → Retirement: ≥2 independent runs/cell, both median-of-seeds      │
│    → D2.4: 3 premature records stay as rows, never verdicts          │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STAGE 5: Analytics & Append-Only Registry               │
│  Load raw records → Per-cell analytics:                              │
│    → Winner via N8 median-of-seeds                                   │
│    → Spread ratio, CV, % of family-realistic ceiling                    │
│    → Cell status: RED(missing) / ORANGE(<50%) / GREEN                  │
│    → Native-vs-spoof deltas (same-run only)                          │
│  Append-only DB (sqlite3 records INSERT, json.dumps payload)         │
│  Feed seeds to Stage 2, verdicts to Stage 6/7                        │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
                    │  ┌────────────────────────────┐  │
                    │  │  CONVERGENCE CHECK LOOP     │  │
                    │  │  (agent.converged())        │  │
                    │  │                            │  │
                    │  │  IF no RED cells OR        │  │
                    │  │     budget exhausted:      │  │
                    │  │    → break (go to Stage 6) │  │
                    │  │                            │  │
                    │  │  ELSE:                      │  │
                    │  │    → harvest wins          │  │
                    │  │    → mutate ≤2 knobs       │  │
                    │  │    → append to phases.yaml  │  │
                    │  │    → loop back to Stage 2  │  │
                    │  └────────────┬───────────────┘  │
                    │               │                  │
                    └───────────────┼──────────────────┘
                                    │ NOT converged
                                    ▼
                    ┌───────────────┴──────────────────┐
                    │                                   │
                    ▼                                   │ CONVERGED
┌─────────────────────────────────────┐               │
│         STAGE 6: Synthesis / Build   │               │
│  Query certified winners from DB:   │               │
│    → Group by 7 dtype/op × 4 patterns│              │
│    → Emit 3_LibraryLogic/gfx90c_*.yaml│             │
│    → Schema-validate (len(data)>=9) │               │
│    → TensileCreateLibrary --merge-files│            │
│    → Anti-alias scan (no gfx900/vega10)│           │
│    → Regression gate (pinned shipped manifest, 2,285 kernels)   │
└─────────────────────────────────────┘               │
                                      │               │
                                      ▼               │
┌─────────────────────────────────────────────────────────────────────┐
│              STAGE 7: Acceptance A/B & Final Report                  │
│  A/B vs the recalled gfx900_ref_* chain:                             │
│    → Floor = dedicated gfx900_ref_* chain, --resume continues it    │
│    → Per-cell (family,dtype,shape) best-of-cell median per arm       │
│    → Verdict: delta_pct = (nat-spoof)/spoof, |Δ|≤5% = TIE=parity   │
│    → Cross-run pairs withheld; chain reconciles base/resume split   │
│  Acceptance REPORT:                                                  │
│    → Per-family coverage vs pinned shipped manifest (2,285)         │
│    → Native-vs-spoof WIN/TIE/LOSS per cell                           │
│    → Cells: RED (missing) / ORANGE (<50% ceiling) / GREEN           │
│    → Overall PASS/FAIL                                               │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │              END                     │
                    │  Final native gfx90c library built │
                    │  Acceptance verdict reported       │
                    └─────────────────────────────────────┘

--auto MODE:
  ┌─────────────────────────────────────────────────────────┐
  │  for _ in range(budget):                                │
  │    run(manifest) → Stages 1-5                          │
  │    write_report                                        │
  │    if agent.converged(): break                          │
  │    agent.feed(manifest) → harvest/mutate → loop back   │
  └─────────────────────────────────────────────────────────┘
```

### 1. Design goal
A **python driver** (`port_tensile.py`, single process) that:
1. holds a **data-only manifest** of phases — `phases.yaml`. Everything about a phase
   is DATA: id, label, dtype, shapes, `ScheduleName`, config-template, seed count;
2. runs each phase by shelling out to Tensile's existing CLI (client +
   `TensileCreateLibrary`) — the driver **never reimplements** benchmarking, config
   semantics, or result parsing;
3. collects Tensile's own outputs (`2_BenchmarkData/*.csv`, library, telemetry),
   persists **`json.dumps` payloads** via one `registry.append_record()` → SQLite
   `records` INSERT (knowledge_base.md §10);
4. analyses per-cell winner (median-of-seeds), %-of-theoretical (`gfx90c_theoretical_limits.md`),
   native-vs-spoof delta, adaptive-repeat (CV / top-2 gap);
5. **decides the next candidate set deterministically** — harvest wins, mutate
   winner-neighbours by ≤2 knobs, append config rows to `phases.yaml`;
6. terminates on convergence (no RED cells under threshold, or budget spent), with
   cooldowns between GPU phases.

`--auto` = run 2↔5 repeatedly until 6, no human in the loop. Agent harvest/accept
(round-N candidates) and convergence + retirement finalize are two small modules
plugged into the loop, not more hand-scrolled blocks.

### 2. Do-not-reinvent rule (verbatim from the user voice)
> Never solve a known-solved basic problem on our own for zero reason. If the OS, the
> Python stdlib, or Tensile already solves it, use that.

The driver uses only existing solvers:

| Concern | Implementation | Solver that already exists |
|---|---|---|
| Phase list | `phases.yaml` = data | data file |
| Round-trip one phase | `for ph in manifest: run(ph)` | Python |
| Ledger records | `json.dumps(dict)` in SQLite `records.data` | stdlib `json` + `sqlite3` |
| Concurrency safety | one writer process; WAL; INSERT-only `records` | stdlib `sqlite3` |
| Run/skip decisions | `policy.should_run(phase, fp) -> bool` + unit tests | Python |
| Analysis + report | `analytics.py` / `report.py` modules | stdlib `csv`, `statistics` |
| Telemetry | python `pathlib` sysfs reads | kernel sysfs |
| Peak authority | `from gfx90c_common import PEAK_GFLOPS` | existing module |
| CLI | `argparse` + one `port_tensile.yaml` | stdlib `argparse` |
| Manifest order asserts | python `assert`/`pytest` on manifest order | pytest |
| Error trail | top-level try/except → one record | python |

### 3. Module list (numbered, ordered)
1. **Manifest first.** Write `phases.yaml` from the phase table captured in
   `potential_configs.md` / `mapping.md` (mechanical transcription). A test asserts
   manifest order matches the documented order **during migration only**.
2. **`registry.py`** — one `append_record()` (sqlite3 INSERT), one `read_records()`
   iterator, queries `phase_retired`, `config_retired(phase,fp)`,
   `first_benchmarked(phase,fp)`. Never UPDATE/DELETE `records`. `phases.yaml`
   stays the manifest (a `phases` table is not the source of truth).
3. **`report.py`** — renders the per-run/per-cell report → `write_report(...)`.
4. **`analytics.py`** — adaptive CV/top-2 scan, winner synthesis, per-cell delta,
   ceiling util vs `gfx90c_theoretical_limits.md`.
5. **`policy.py`** — `should_run(phase, fp)` in order: scope check → tier-1 retired
   (fp-less) → tier-2 retired (phase,fp) → identical-fp skip (opt-in). Unit-test the
   matrix (mirror of the prior policy cases).
6. **`scheduler.py` + `agent.py`** — cooldown latch (first-GPU-phase exempt),
    `--targets`/`--family`/`--pattern`/`--shape` scope, adaptive NumBenchmarks bump,
    **occupancy-aware GSU/WGM sizing**;
   `agent.py` reads `report.py` → harvest / mutate (≤2 knobs) / tie → append rows →
   return subset to re-run.
7. **`port_tensile.py`** — preflight (arch, device, tensileness); per-manifest-row run
   Tensile, collect, register, cooldown; at end write report; `--auto` loops 2↔6 until
   convergence or budget. Replaces the special frozen-block handling.
8. **`--arch gfx90c`** is emitted into every Tensile invocation (fixed target — not
    a driver flag); the spoof floor baseline = the dedicated `gfx900_ref_*` chain.
9. **Entrypoint.** The python driver is the only suite entrypoint.
10. **Fold the redundant tooling** — favouring counters and fingerprint helpers
    all become python modules or tests.

### 4. Reference-floor contract (unchanged)
The spoof floor is the **dedicated `gfx900_ref_*` run chain**: benchmarked once per
shipped kernel (`--gfx900-reference`), continued via `--resume` when interrupted, then
recalled — never re-rolled — by every acceptance report. It is a **floor, never a
retirement signal**.

### 5. Phase 5 / 6 / `--auto` mapping
- **Agent harvest/accept round-N candidates** (`agent.harvest()`): cells with native
  median ≥ spoof median (ruler-adjusted) → incumbent; RED/non-converged cells →
  `candidates.spawn_neighbours(winner, ≤2 knobs, occupancy-aware)` appended to
  `phases.yaml`.
- **Convergence + retirement finalize** (`agent.converged()`): no below-ceiling cells,
  ≥3 configs/cell, ≥2 runs/cell, CV ≤ 15% → write tier-2 retirement records (≥2
  independent runs/cell gating) and stop. Budget exhaustion returns converged=False and
  a FAIL readout, not a pass.
- **`--auto`**: `for _ in range(budget): run(manifest); write_report; if
  agent.converged(): break; agent.feed(manifest)`.

### 6. Migration order (don't rewrite blind)
1. `registry.py` + `report.py` extracted, unit-tested, still fed by the existing
   data layout.
2. `phases.yaml` transcribed (mechanical).
3. `policy.py` + `scheduler.py` extracted; gate-matrix re-run.
4. `port_tensile.py` takes over phase-by-phase-group; `--targets` scoping parity
   checked against the reference-floor chain.
5. Agent loop + `--auto`; convergence budget configurable.
6. Single entrypoint: the python driver.

### 7. Statistics/HTML tooling (report.py pipeline)
The reporting surface is `analytics.py` → `report.py` → `acceptance_report.json` +
self-contained `acceptance_report.html` (single-file dashboard, Carbon design
language). The driver feeds an append-only data layout (per `knowledge_base.md` §10):
- `gfx90c_runs/run_YYYYMMDD_HHMMSS/` with `configs/phase<N>_*.yaml`,
  `phase<N>_*/2_BenchmarkData/*.csv`, `logs/telemetry.csv` (header-in-file),
- `gfx90c_results/registry.db` (`records` INSERT-only) as the canonical ledger,
- `gfx90c_results/acceptance_report.json/.html` regenerated per run (and on
  `'e'`/`'q'` early exit), plus any jsonl `export` of new rows.
Any module that changes these outputs must be validated by re-running the pipeline
before merging.

---

## Triaged fixes (self-contained dispositions)

### P0 for oto (all four in scope)
1. **Deterministic driver (`port_tensile.py`)** per the architecture above.
2. **Finite per-phase timeout default** — `--phase-timeout` default is finite
   (generic runaway protection) and per-phase skippable/killable.
3. **Interactive single-phase kill** — 's' skip / 'q' quit exactly one phase, not
   Ctrl+C-the-whole-run.
4. **Auto-retire trust gating** — the 3 existing `retire` records came from a single
   invocation; under 77% winner instability, require **≥2 independent runs** per
   trusted shared cell (incomplete_work §4.6).
5. **Peak-table prose drift** — stale prose still claims BF16/INT8 = 3226. gfx90c is
   single-rate (1613). `gfx90c_common.PEAK_GFLOPS` is the single source; regenerate
   dependent artifacts.

### Known-fixed states (do not regress)
| Finding | Correct form |
|---|---|
| Ruler shape strings `"MxNxK"` vs dataset `"MxNxB"+SizeL` | `gfx90c_common.py` rulers + `bound_class()` |
| `adj_cells()` no-op (dt key not `(dt,cls)`) | keyed `(dt,cls)`; missing = None |
| geo-mean fallback inferring missing rulers | removed; missing reported |
| Phantom `("BF16","DDR")` ruler → nonexistent phase | deleted |
| report dtype `extract_dtype_from_phase_id` | restored via token-based family parse (report.py; legacy regex produced 'unknown') |
| `AssertSizeMultiple: [1]` crash (scalar int vs dict) | `[{}]`/fixed keys: config-validation gate |
| Toolchain — `hipconfig --version` on stderr | try/except + explicit ROCM_PATH |
| HardwareMonitor `stoi` on APU | `HardwareMonitor: False` in configs |
| Telemetry `.hdr` sidecar, kHz/mW units, parent-dir glob | header-in-CSV, canonical units, `hwmon[0-9]*` |
| joblib/loky vs Python 3.14 resource-tracer | **solve not avoid** (pin/fix parallelism; fallback `CpuThreads: 1` documented) |
| Self-terminating run (no new bench work) | prove the run will execute something before starting |
| Orphaned subprocess fragilities on abrupt breaks | `|| true`, `set +e`-style isolation (python makes it moot) |
| Acceptance native arm scoped to one run → all-zero report | whole-db arm (`_native_records_all_runs` / `_native_analytics_all_runs`); winners may come from an older run |
| A/B delta from max raw sample while columns showed medians | all stats per-kernel-median-first; kernel medians keyed by (run, phase, fp) |
| A/B columns hard-wired to one basis, re-breaking the delta | columns render `native_value`/`spoof_value` (the operands actually divided) under basis-aware headers |
| Occupancy gate unable to fire (no `MacroTile`, no VGPR count) | `scheduler.occupancy_feasible`; `validate_config` + `_estimate_occupancy` both delegate |

### Open defects (triaged 2026-09-27, resume/candidate evidence)
1. **`_write_phase_config` early-returns without writing the file.**
   `execute_phase` ignores the return, so Tensile is launched against a config that
   was never written → `FileNotFoundError`, rc=1. This is the entire 121-phase
   rc=1 bucket of `gfx900_ref_20260926_201843_resume` (1,091 configs exist for 1,212
   targets; the 121 missing are exactly the rc=1 set). Fix both ends: treat a
   `None` return as a pre-flight rejection (record a skip, never spawn Tensile), and
   filter assembly-class-illegal configs out of reference-deck generation. Cost
   today: a wasted Tensile launch per phase and an unattributable failure bucket.
2. **ZZ/double native phases die on Occupancy limit — FIXED (preflight gate + deck revision).**
   All 8 executed `run_20260926_201835` phases ended `Generating kernel source resulted in error 4`
   = `overflowedResources == 4` = Occupancy limit (`Tensile/KernelWriterAssembly.py:15422`,
   `functionSuffix`). Distinct from the benign "error 3" note below. Root cause was a
   gate hole, not a bad tile choice: `CandidateGenerator._estimate_occupancy` inferred
   threads from `ThreadTile` with a `64 // tt` heuristic, **ignored `MacroTile`, and
   never counted VGPRs**, so it could never fire.
   Landed: `scheduler.occupancy_feasible` + `VGPR_PER_ELEMENT` / `VGPR_BUDGET`, wired
   into `validate_config` and `_estimate_occupancy`; fails closed on an unmodelled
   dtype (a wrong guess picks the wrong weight and would re-admit the failure).
   Verified: reproduces all 9 observed pass/fail cases, rejects exactly the 8 dead
   phases and nothing else in the pre-fix 410-phase deck, 18/18 tests
   (`test_occupancy_gate.py`). Deck 410 → 418: dead `128x64x8/8x4` + `64x128x8/4x8`
   replaced by legal `128x32x8/8x4` + `32x128x8/2x8`, plus new-axis `64x64x8/4x2` and
   `128x32x16/8x4`, all × 4 contraction patterns. Full derivation, the calibrated
   weight table, and the pre-fix deck proof live in `potential_configs.md` §5.7 —
   that section is the authoritative home, not this entry. ZZ is now **legal but
   unbenchmarked**: the next real step is a TTY run, not more code.

### CPU-only work queued (no GPU, ordered by value)
These are the only remaining items that do **not** need a TTY. Everything else in
the route portfolio is measurement-bound (`potential_configs.md` §8.2).

1. **Measure real per-thread VGPRs** for the tile families, via `roc-obj-ls` /
   `llvm-mc` on Tensile-emitted assembly (build only, no benchmark). Replaces the
   calibrated `VGPR_PER_ELEMENT` table in `scheduler.py` with a measurement, which
   is the only way to retire the 2× headroom assumption (`potential_configs.md`
   §5.8). Highest-value item outstanding.
2. **Set `PrintSolutionRejectionReason`** on ZZ phases so the next run's rejection
   reason is logged instead of inferred from `overflowedResources`.
3. **Sweep the floor reference deck through `check_candidates.py`** to *prove* the
   floor's winning configs are natively gate-legal, rather than assuming they are
   because both arms emit `TensileLibrary_gfx90c.co.raw`.
4. **Fingerprint-diff native vs floor winner sets per cell** — turns "floor wins at
   128-bit" into an exact per-cell knob delta, which is what §9 candidates are
   derived from.
5. **Report the occupancy margin** (not just pass/fail) in `check_candidates.py`
   output so near-boundary configs are visible.
6. **Audit the 117 legacy `auto` phases** — they are the largest single block in the
   deck and are all dtype-char mutants, so their marginal value is unproven.

### Known hazards — must never regress
- **APU wedge at sustained 2048³-style benchmarks** (HW-Exception, exit 134). Rule:
  cooldown + detached+killable GPU processes; no untimed marathon cells.

### Benign warnings (do not spend time on)
- "Kernel file context manager opened without any kernel files" (MergeFiles: False).
- "error 3" overflowedResources on non-MFMA half kernels (upstream-declared fine).

---

## Next Move — Steps 1–6

### Step 1 — Approve + build the driver (`port_tensile.py`), per the architecture above
- Python driver + `phases.yaml` data-only manifest. `policy.py` `should_run(phase,fp)`
  encodes tier-1 → tier-2 → phase-1-first-only → identical-fp skip. All evidence
  writes via `json.dumps` + SQLite `records` INSERT. `--auto` loops
  run→report→harvest→mutate. Harvest **appends `phases.yaml`**, never a DB-only
  manifest.
- **Do-not-reinvent + PoC gate**: argparse, stdlib `json`/`csv`/`statistics`/`sqlite3`,
  git for diffs, sysfs for monitoring, `PEAK_GFLOPS` imported from `gfx90c_common.py`,
  ceilings imported from `gfx90c_theoretical_limits.md`. **Every module is PoC'd and
  fully functional in `/tmp/opencode/` before it lands.** No change lands without a PoC
  + a scoped parity run. `/tmp/opencode` currently contains analysis scratch
  (`an*.py`, pickle datasets, `poc_cellkey`/`poc_resume`) plus a pre-resume A/B dump —
  see `incomplete_work.md` §4.9. Do not land that tree as-is.

### Step 2 — gfx900 reference floor (user executes) — GATE
- `python3 port_tensile.py --gfx900-reference` launches the dedicated floor chain;
  `--gfx900-reference --resume` continues an interrupted chain (retries failed once).
- `--auto` auto-resumes an incomplete floor and refuses any tuning until
  `_reference_remaining() == 0`; verdicts then fold per-cell into `results.md`
  (append-only, `knowledge_base.md` §10).

### Step 3 — Native family-matrix phases (coverage-first, the two-measure acceptance)
- From `mapping.md` decks: emit one phase per family×pattern combo actually in the
  workload (start with the SS/DD/HH families and the Emilio shapes 256³/512³/1024³/
  2048³ + suite shapes); each phase benchmarks the mapped tile deck (translated, not
  copied ISA900) natively.
- Prior win/lose/empty-cell triage feeds deck trimming: do NOT re-sweep what already
  failed (holding both to the frozen prior conclusions and any fresh evidence).
- For every replicating family, record the measured %-of-§5-ceiling as the
  "approach the theoretical limit" score alongside the native-vs-spoof delta;
  RED = below both.

### Step 4 — Deterministic agent loop (`--auto`)
- `agent.py` harvests per-cell winners (median-of-seeds, ruler-adjusted) → for RED or
  non-converged cells, `candidates.spawn_neighbours(winner, ≤2 knobs,
  occupancy-aware)` → append rows to `phases.yaml` → re-run the subset. Budget:
  configurable wall-time/GPU-minutes + finite per-phase timeout default.
- Convergence per cell (all must hold): (a) no below-ceiling cells (b) ≥3 distinct
  kernel configs tested per cell; (c) ≥2 independent runs/cell (≥6 seeds); (d) CV ≤ 15%
  per cell. Budget exhaustion is a STOP, never reported as converged (a FAIL verdict on
  unmet criteria). Global stop: fully converged, OR budget exhausted (flags FAIL), OR
  unrecoverable build gate FAIL.

### Step 5 — Manual-LLM contingency (add-only, user-invoked, worst case ONLY)
- If a cell is RED after deterministic mutation plateau: user calls an LLM with a
  single canned prompt (≤5 recipe mutations constrained to known-valid gfx90c knobs).
  Results are DROPPED INTO `phases.yaml` as new candidate rows; they enter the same
  deterministic pipeline. Never an in-loop consultation.

### Step 6 — Synthesis + acceptance
- `agent.converged()` → write tier-2 retirement records (≥2 independent runs/cell
  gating) → master synthesis of the harvested winner set → `results.md` +
  `gfx90c_results/acceptance_report.json/.html` regenerated → final anti-alias
  re-assert (0 gfx900 leaks) and whole-library native-vs-spoof readout with per-family
  %-of-theoretical ceilings.

## Exit criteria

- [ ] `port_tensile.py` + `phases.yaml` driver operational; it is the only entrypoint.
- [ ] Reference floor fully decided; verdicts
      re-derived per cell vs the recalled `gfx900_ref_*` chain.
- [ ] Native family-matrix phases cover the shipped footprint families (mapped),
      all native `isa`; every replicating family logged at %-of-ceiling.
- [ ] **Aggregate native library beats the gfx900-spoof floor across the shipped
      suite** (per-cell, recalled-floor, ruler-adjusted, median-of-seeds, ties = parity) —
      the whole-library readout, not subset success.
- [ ] Deterministic loop converged (no RED cells or budget exhausted); ≥2 independent
      runs / ≥3 configs per converged cell.
- [ ] Occupancy objective: measured per-cell utilization raised toward the §5
      ceilings (GSU/WGM/MT/TT right-sizing recorded as a first-class knob campaign).
- [ ] Statistics/HTML tooling intact end-to-end after the refactor (Verify by inspecting the
      live `gfx90c_results/acceptance_report.json` + `acceptance_report.html` that the current
      `report.py` pipeline writes).
- [ ] Peak-table prose corrected everywhere to single-rate 1613 for BF16/INT8.
- [ ] Final synthesis + zero-leak anti-alias + whole-library native-vs-spoof readout.

## Relevant Files
- `implementation_plan.md` (this plan — self-contained), `gfx90c_theoretical_limits.md`
  (ceiling authority), `mapping.md` (footprint contract), `potential_configs.md`
  (candidate deck), `changelog.md` (evolution), `results.md` (data, append-only),
  `claude.md` (entry contract), `knowledge_base.md` (data law §10).
- Live repo: `gfx90c_common.py`, `tensile_library.py` (gfx900 dat parse + reference
  chain), `report.py` (writes `gfx90c_results/acceptance_report.json/.html`), the
  native gfx90c patch (`Tensile/Common.py` + `Tensile/AsmCaps.py`, in the Tensile
  tree), `gfx90c_results/registry.db`, `gfx90c_runs/` (`gfx900_ref_*` + `run_*`).
- Sanctioned prior conclusions: `prior_INSIGHTS_CAVEMAN_ULTRA.md`,
  `prior_RESEARCH_ARCHIVE.md`.