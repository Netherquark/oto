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

**Status 2026-10-09 — all six items complete:**

1. ✅ **Measure real per-thread VGPRs** — `harness/measure_vgprs.py`
   (llvm-readelf on Tensile's emitted assembly `.o` metadata, corpus-wide,
   CPU-only). Measured medians per (dtype, TT) now in
   `scheduler.MEASURED_VGPR_BY_DTYPE`; invariant test
   (`test_occupancy_gate.py::TestMeasuredRule::test_corpus_measured_totals_agree_with_gate`)
   proves gate-legal ⇔ measured < 256 VGPRs. The occupancy model (§5.7) is now
   measurement-ratified, not calibrated.
2. ✅ **Set `PrintSolutionRejectionReason`** — already present in GlobalParameters
   (`port_tensile.py:1052`).
3. ✅ **Sweep the floor deck through `check_candidates.py`** — `--floor` mode:
   **all 30 per-cell floor winners pass all 4 gates**; whole-deck residue
   1 464/6 855 (21 %) is generator-rule artifacts on non-winners (GLVW/VW,
   assembly) + 72 genuine occupancy-LDS (never-won entries, gfx900-64K-LDS
   kernels the APU rejects).
4. ✅ **Fingerprint-diff native vs floor winners per cell** —
   `harness/cell_knob_diff.py`: 30 cells shared, 22 native / 8 floor
   (SS:512/768/1365/2048, HH:1024/2048/4096, CC:256); CC:256 is the single
   outside-band LOSS and the only sanctioned steal.
5. ✅ **Occupancy margin in `check_candidates.py`** — `_occupancy_margin()`
   prints `wg/cu=N acc=…vgpr …% of 64K file`.
6. ✅ **Audit the 117 legacy auto phases** — 560 `phase_auto_*` dirs total; the
   auto pool wins 13/34 cells natively (38 %), incl. HH:256 763.4 and SS:1024
   1135.1 — **not marginal**; keep them (rename S/Z tokens at hygiene time).

Full write-up: `gfx90c_tuning_guide.md` (the tuning cookbook).

### Known hazards — must never regress
- **APU wedge at sustained 2048³-style benchmarks** (HW-Exception, exit 134). Rule:
  cooldown + detached+killable GPU processes; no untimed marathon cells.

### Benign warnings (do not spend time on)
- "Kernel file context manager opened without any kernel files" (MergeFiles: False).
- "error 3" overflowedResources on non-MFMA half kernels (upstream-declared fine).

---

## Option H — Mutator overhaul (formalised, single-shot)

> **Status: Phases 1-3 LANDED (2026-10-05).** `Hplan.3`, `Hplan.4` and
> `Hplan.5` are implemented and green. Phase 4 (synthesis) is approved in
> principle but not started; nothing above is superseded.
> What landed: the append-only `proposals` table and ledger/novelty API (`registry.py`),
> `mutator.py` (classifier, novelty, negative cache, per-run overlay), the `agent.mutate_and_feed`
> rewrite that routes candidates to the overlay instead of `phases.yaml`, and
> `analytics.count_benchmark_rows` as the single owner of CSV shape. Three new test modules
> (`test_proposals_ledger.py`, `test_mutator.py`, `test_mutation_arm.py`).
>
> Two behaviours deliberately did **not** change, and both would have been easy to get wrong:
> the identical-fp skip is bypassed only when the ledger is *and* the outcome signal are
`scheduler.mutate_winner` was still the lattice sampler at this point --
Phase 1 replaces the loop's memory, not its generator. (Phase 2 has since replaced the
sampler too; see `Hplan.4`.) The pre-Phase-1 path remains reachable by constructing
>
> **Read `proposal.md` §H.1.2a and `changelog.md` (2026-10-05) before implementing Phase 1.**
> The evidence that originally ordered this plan — "mutants produced zero GFlops" — is
> **retracted**; it was an artefact of reading the `GFlops`-headed column, which is a problem
> index rather than a throughput. Through the canonical loader the mutants are productive but
> **ungraded**. The consequence for this plan is concrete: the negative cache's motivation in
> `Hplan.3` step 9 no longer has historical support, so it ships as a *forward* guarantee with
> a test that asserts it does **not** fire on today's corpus, and D5 (single-shape, ungradable)
> is promoted to co-equal status with D6. H.3.8's definition is unchanged and still correct —
> it is the historical justification that was wrong, not the predicate.
>
> Option H is an open proposal with
> no implementation beyond Phase 1. The evidence and design rationale live in `proposal.md`
> (addendum dated 2026-10-05); **this section is the executable plan only** and holds no
> restatement of its numbers — per §3 (one fact, one canonical home) and per the
> never-transcribe-a-count rule (§5), every figure is cited to `proposal.md` §H.x and read
> live by the tools. Approving this section does **not** approve Option H itself; that is
> question 1 of `proposal.md` §H.10.

### Supersession notice (read before Stage 2)

This section, once approved, **supersedes three parts of this file**:

| location | current text | superseded by |
|---|---|---|
| Stage 2 mechanics; §5 bullet 1; flowchart Stage 2 | "mutate by ≤2 knobs (neighbour search)", "mutate ≤2 knobs" | `Hplan.6` sampling |
| Stage 2 mechanics; §5 bullet 1 | "Emit candidate configs to `phases.yaml`" | `Hplan.3` step 7 — per-run overlay |
| Stage 5 | "Feed seeds to Stage 2" | `Hplan.5` coverage/fitness view |

Until approval, the code and this text remain consistent: `scheduler.mutate_winner`
still does ≤2-knob neighbour search and `agent.mutate_and_feed` still appends to
`phases.yaml`. Do not "fix" the code to match a future plan.

### Hplan.1 Defects this addresses

D1–D6 as enumerated and evidenced in `proposal.md` §H.2. In plan terms:

1. **`--mutation-budget` does not bound anything.** `scheduler.py:379` consumes it in one
   boolean test (`if mutation_budget >= 2`). It gates two-knob pairs; single-knob mutants
   are emitted unconditionally. The flag's help text ("Maximum knobs to mutate per
   candidate") is therefore misleading.
2. **No novelty memory.** Iteration *n+1* re-proposes fingerprints already emitted.
3. **Output is largely non-functional.** `proposal.md` §H.1.2a measures this at the CSV
   layer with a same-run positive control. The loop has no field distinguishing "ran and
   produced nothing" from "worked".
4. **Mutants are written into the curated deck**, then skipped on the next pass.
5. **Mutants are single-shape**, so they are born ungradable against a multi-shape floor.
6. **Outcome is never recorded**, so the loop cannot learn from failure.

### Hplan.2 Deliverables

| artefact | kind | owner doc |
|---|---|---|
| `mutator.py` | new module: legality, novelty, coverage, outcome, synthesis | this section |
| `registry.py` | `proposals` table + `json_extract` expression index | this section |
| `agent.py` | `mutate_and_feed` delegates to `mutator.py`; stops calling `append_to_phases` | this section |
| `scheduler.py` | lattice retained as a fallback sampler; `mutate_winner` unchanged | this section |
| `ab_audit.py` | report `origin` split, per-cell `n`/spread, outcome histogram | this section |
| `tests/test_mutator.py`, `tests/test_proposals_ledger.py` | new tests | this section |

**No new parser.** Every read of a phase's knobs, a CSV, or a fingerprint goes through the
canonical loaders already mandated by `claude.md` §2.1 (`tensile_library`, `analytics`,
`registry`, `allruns.py`, `check_candidates.py`). If a needed value cannot be obtained from
them, that is a defect in one of them — fix it there, do not add a parallel reader.

### Hplan.3 Phase 1 — ledger + outcome (do this first; the rest is worthless without it)

Rationale: this is the phase that makes the mutator a search rather than a dedup cache,
and it is independently useful even if nothing later is approved.

1. **PoC in `/tmp/opencode/`** (`claude.md` §5): a `proposals` table created against a
   **copy** of the live registry, with INSERT and the single monotonic
   `outcome` write-back, exercised end to end before any repo edit.
2. **Schema** exactly as `proposal.md` §H.3.1, including `origin`, `outcome`, and
   `build_class`. Migration is additive (`CREATE TABLE IF NOT EXISTS`); it must not touch
   the `records` schema or rewrite any existing row.
3. **Append-only discipline** (`knowledge_base.md` §10): rows are never `DELETE`d and never
   rewritten; `outcome` only advances `pending → terminal`. A single monotonic status
   column is not a mutation of history. Enforce with a trigger or an `UPDATE ... WHERE
   outcome='pending'` guard plus a test that a second write-back is a no-op.
4. **Novelty query**: novel iff `fp` absent from **both** `proposals` and the registry's
   decided set. Add the `json_extract(data,'$.fp')` expression index; do **not** change
   `has_fp_passed` semantics, only its cost.
5. **Outcome classifier** (pure function, CPU-only): reads a phase's
   `2_BenchmarkData/*.csv` via the canonical loader `analytics.load_benchmark_csv` and returns
   one of `functional` / `non_functional` / `legal_rejected` / `legal_slow`. `functional` iff
   that loader yields at least one record; `WinnerFreq` recorded alongside.
   **Implementation constraint, non-negotiable:** the predicate must be expressed *in terms of
   the loader*, never by re-reading the CSV and indexing the `GFlops` column. That column is a
   problem index, not a throughput — deriving the predicate from it is precisely the error
   retracted above. If the classifier needs something the loader does not expose (row count, to
   separate "rows present but all zero" from "no rows"), that accessor is added to
   `analytics.py` as the single owner of CSV shape, not reimplemented here.
6. **Durability regression** (`proposal.md` §H.3.2): on a DB **copy**, delete every native
   row and assert the ledger and novelty still hold. Never run this against the live DB.
7. **Overlay** (step 7 above): candidates route to a per-run overlay the runner reads
   and the curator never sees. `phases.yaml` stays curated and reviewable; discarding a bad
   batch deletes an overlay, never edits history.
8. **Wire the mutation arm** to emit through `mutator.py`, bypassing
   `opt_in_identical_skip` **only because** novelty is now structural. If this table is
   ever disabled or lost, the skip must be re-enabled for the mutation arm — the bypass is
   a correctness dependency on the ledger, not an optimisation.
9. **Negative cache**: if *k* consecutive candidates from one neighbourhood return
   `non_functional`, down-weight that neighbourhood instead of re-sampling it. *k* is a
   named parameter with a default, not a literal buried in code.
   **The historical justification for this is retracted** (see the status note above): replayed
   against today's corpus the cache correctly never fires, because every measured mutant row is
   non-zero. It therefore ships as a *forward* guarantee, and the test asserts both halves —
   it fires on *k* consecutive `non_functional` outcomes, and it does **not** fire when replayed
   over the archived runs. A test that only checks the first half would pass while the cache
   silently misfires on real data.
10. **Guardrail compliance to assert in tests**: no corpus count is transcribed into code,
    a comment, or a test fixture; counts are read live from the registry/manifest exactly
    as `auto_prompt._read_counts()` already does. No test asserts a literal corpus size.
11. **Revert the skip-bypass claim if phase 1 lands partially.** If the ledger ships
    without outcome, the mutation arm must keep the skip on, because a novelty-only ledger
    over a non-functional search makes the run *look* productive while measuring nothing.

#### Phase 1 integration pass — LANDED (2026-10-06)

The ledger shipped in Phase 1 with every one of the pieces above present and **none of them
reached a run**. Each gap is listed with the failure it produced, because each was silent:

| gap | what it actually did |
|---|---|
| overlay never merged | candidates were emitted and recorded, then never scheduled — the arm reported progress while measuring nothing |
| `run_id` dropped on emission | every proposal had `run_id=NULL`; "which run produced this" was unanswerable |
| proposal + phase = two commits | a crash between them left a permanently-`pending` candidate: its `n` never grows, so the cell is re-routed to `replicate` forever, indistinguishable from genuine instability |
| `resolve_phase_dir` never called | outcomes were never written back, so the ledger only ever grew `pending` rows |
| `WinnerFreq` via a private reader | a second set of Tensile CSV format assumptions; fails as zeros, which reads as "no kernel won" |
| `WinnerFreq` not persisted | H.3.8's evidence requirement was met only in memory, for the life of one process |
| negative cache process-local | every restart reported a saturated neighbourhood as untouched — the cache silently switched off at exactly the moment it was needed |
| `skip_mutation_arm()` never consulted | the bypass was computed on every emission and then ignored by the loop that skips |

**Schema decision — `proposal_observations`.** H.3.8 wants WinnerFreq "recorded alongside the
verdict". It cannot live on the `proposals` row: a proposal's *evidence* is re-observable while
its *verdict* is decided once, so columns there would invite overwriting the basis of a
decision already made. It is a separate append-only table, one row per observation, written
**before** the verdict — a crash between them leaves recoverable evidence and a `pending` row,
whereas the reverse order leaves a decided verdict with nothing behind it.

**Read-only registries.** Found while verifying: `SQLiteRegistry.__init__` ran the additive
schema migration unconditionally, so every `ab_audit` run rewrote the live floor registry's
bytes. No row was touched, but a report had changed its own subject. `SQLiteRegistry(base,
read_only=True)` now skips `_init_db` and every mutating method raises `PermissionError`; the
audit opens the registry read-only. Asserted byte-for-byte.

**Bypass scoping.** The identical-fp bypass applies to **overlay phases only**, and only while
`skip_mutation_arm()` is False. Applying it deck-wide would re-benchmark settled curated phases
every run, which is the opposite of what the skip is for.

**`tests/test_phase1_integration.py`** (53 cases) covers all of it by driving the driver's
`run_phases` loop, not the helpers in isolation — testing `_resolve_proposal_outcome` and
`should_run` directly passes even when the loop calls neither, which is exactly the state
Phase 1 was in. Verified by disabling the merge and the write-back: 2 of the loop tests fail.

### Hplan.4 Phase 2 — legality prior

1. **Do not model the reject set; read it.** The reject predicates are already documented
   with source citations in `proposal.md` §H.2 and verified against the Tensile checkout
   at `e8a8999e`. Re-verify each one at implementation time and record the commit in the
   module docstring — the audit that seeded them is dated, and one of its five root causes
   was already found to mis-state its own condition.
2. **Sample legal-by-construction**: draw each knob only from values observed for that
   `(family, dtype)` in `gfx90c_results/gfx900_shipped_manifest.json` via the canonical
   parser. This is what removes the ±1-neighbour reject classes structurally rather than
   filtering them afterwards.
3. **Hard walls**: encode the verified half-precision `VectorWidth` floors (including the
   GSU case) and the MT/schedule rejections as named predicates with unit tests. Do not
   encode the audit's prose summary; encode the code.
4. **Keep `validate_config` as an assertion, not the search.** A candidate it rejects is
   recorded `legal_rejected` with its `build_class` so phase 1's negative cache can learn
   from the rejection.
5. **Legality is not the agent's judgement** (`AI Must Not Decide`): every predicate
   traces to Tensile source or the shipped manifest, never to model reasoning.
6. **Report the legal rate** from a CPU-only sampler sweep, with the baseline read live —
   never a transcribed percentage.

#### Phase 2 outcome — LANDED (`legality.py`, 2026-10-05)

| step | status | evidence |
|---|---|---|
| 1 read, don't model | done | every predicate re-read at `e8a8999e`; commit recorded in the module docstring and in `legality.TENSILE_COMMIT` |
| 2 legal-by-construction | done | `shipped_support` / `sample_legal`; knob values come only from the pinned manifest |
| 3 hard walls | done | `half_vector_width_floor`, `mt_has_shipped_schedule`; GSU case recorded in `DEFERRED_RULES` instead of guessed (below) |
| 4 assertion retained | done | `validate_config` still runs per candidate; rejections recorded `legal_rejected` |
| 5 not the agent's judgement | done | each predicate cites Tensile source or the manifest |
| 6 live legal rate | done | below |

**Measured (rerun `/tmp/opencode/legality_compare.py`; both arms same 29 curated
parents, same process, same `validate_config`):**

| family | lattice | prior |
|---|---|---|
| CC | 13% | 100% |
| DD | 58% | 88% |
| HH | 25% | 72% |
| HH_HPA | 24% | 91% |
| HS_HPA | 23% | 79% |
| SS | 55% | 70% |
| ZZ | 32% | 100% |
| **all** | **417 / 1169 = 35.7%** | **198 / 232 = 85.3%** |

The lattice column reproduces the D3 table exactly when re-run live (1169 proposed,
417 legal), which is the cross-check that the prior is measured against the same
reject model D3 was. The prior's residual is dominated by occupancy/register-file
and by load divisibility on the *full problem instance* — gates that need the phase's
sizes, not just the kernel, and which step 4 assigns to the assertion. Driving those
into the sampler would mean re-implementing the assertion, so they were left there.

**Three findings from implementing it, all corrections rather than confirmations:**

1. The audit's `A_half_VW1_assembly` label implied one wall; it is two conditions in
   different places, and the GSU one is *not* enforceable from our config surface. A
   first cut modelled it as `VectorAtomicWidth < 2 -> reject` and a live sweep showed
   it firing on shipped HS_HPA `GlobalSplitU` 2/3/5/7 vectors — 90 false rejections,
   i.e. exactly the "modelling the reject set" failure step 1 forbids. The real value
   is *derived* (`SolutionStructs.py:3574/3588`) and the guard is gated on the internal
   `_GlobalAccumulation`, so it now sits in `DEFERRED_RULES` with its reason. The
   reachable GSU rules were already `assembly_class_valid`'s (rules 2 and 3).
2. The half `VectorWidth` wall was **dead on arrival**. `EnableMatrixInstruction`
   (`:1918-1930`) tests `len(ThreadTile) == 2`, but our configs carry ThreadTile as the
   string `"8x4"`, whose length is 3 — so every candidate read as *undetermined*, the
   `is False` branch never ran, and the sweep reported a suspicious 100% accepted with
   zero drops. Fixed by normalising ThreadTile; the wall then caught the 32 shipped
   half `VW1` vectors. A legal-rate sweep that reports a perfect score is a bug report.
3. GlobalLoadVectorWidth is a function of MacroTile, so `schedule` and `loads` are not
   independent groups — moving them separately manufactured the indivisible-tile
   rejections the prior exists to avoid (85 of 86 HH_HPA rejects). They are now one
   atomic `tile` group. Separately, the base must be a *complete* shipped vector:
   deck/winner configs carry only MacroTile + ThreadTile, and building on those directly
   emitted configs with no WorkGroup, no VectorWidth and no load widths, which was the
   largest remaining reject cause. The parent now selects a neighbourhood (donors
   sharing its MacroTile); a shipped vector supplies the config.

### Hplan.5 Phase 3 — coverage + fitness

1. Coverage view over `proposals` + `records` per `(family, shape)`: distinct `fp` count,
   sample count `n`, median, spread. Cells are targeted, not enumerated.
2. Three states kept distinct: no candidate → explore; `n = 1` or spread beyond the
   acceptance band → replicate; all-`non_functional` → retired, not "empty" (§H.1.2a).
3. Parent selection by **lower confidence bound**, never raw winner. Today's `harvest()`
   picks the winner, which is how a noise-level win becomes the parent of the next batch.
4. `ab_audit.py` surfaces `n`, spread, and the `novel`/`replicate` split so a replicate's
   value is visible after the fact.

#### Phase 3 outcome — LANDED (`coverage.py`, 2026-10-05)

| step | status | evidence |
|---|---|---|
| 1 coverage view | done | `coverage.coverage_cells`; `registry.all_proposals` + `coverage.samples_by_fingerprint` |
| 2 three states | done | `decide_state`; exactly three states, no fourth ("empty") |
| 3 LCB parent | done | `coverage.select_parent`, `agent.harvest(parent_by="lcb")` |
| 4 ab_audit surfaces it | done | `_proposal_coverage` + `_print_proposal_coverage` |

**Design points worth stating, because each is a place the obvious version is wrong:**

- **The band is read, never written** — and was initially *not read at all*. The
  first `coverage.measured_band_pct()` called `ab_audit.reproducible_band` with one
  argument for a two-argument function, and its `except Exception` turned the
  resulting `TypeError` into `None`. Every cell therefore ran with "no band",
  silently, while this document claimed the band was measured. Fixed by extracting
  `ab_audit.arm_record_sets` + `ab_audit.measured_band`, which are the *same two
  calls `audit()` makes*, so coverage and the audit cannot disagree and
  `_proposal_coverage` can pass the band it already has instead of recursing into
  `audit()`. Measured on the current corpus: **18.29%** (`max(cross-arm 18.29,
  repeat-tail, shipped-floor 5%)`) — the shipped 5% is a floor, not the answer.
  The test that let this through was `assertTrue(value is None or value > 0)`,
  which passes for a function that always raises; it is now four assertions that
  all fail when the read is stubbed back to `None`.
- **Explicit target cells.** `coverage_cells(..., target_cells=...)` emits a cell
  that was targeted but never proposed for, so it can be reported as `STATE_EXPLORE`.
  Deriving cells only from proposals made "we never looked" and "not on the list"
  the same absence — the conflation §H.1.2a is about.
- **`min_n` is the *worst* measured config in the cell, not the mean.** A cell whose
  best config has eight seeds and whose other config has one is not confidently
  measured; averaging that away is how a noise-level win becomes a verdict.
- **Retirement is checked after evidence exists.** `decide_state` returns `explore` for a
  cell with no decided rows before it can ever return `retired`, so "never tried" is
  never recorded as "tried and failed". `legal_rejected` also does not retire a cell: a
  rejected proposal never ran.
- **`n = 1` degrades the bound to the median rather than faking a variance.** Thin
  evidence is reported as thin (`min_n`, state `replicate`); a one-sample LCB that
  claimed precision would be a second definition of confidence.
- **The seeds travel with `CellAnalytics`** (`analytics.compute_cell_analytics` now
  attaches them). An LCB cannot be recovered from a median, a CV and a count, so parent
  selection would otherwise need a second read of every CSV. Hand-built cells without
  seeds degrade to the median rather than raising.
- **`parent_by="median"` remains reachable**, and `selected_by_lcb` /
  `parent_by` / `parent_score` are recorded on every winner, so a run's parent
  policy is visible afterwards and the two rules can be compared on the same data.

### Hplan.6 Phase 4 — synthesis, graded form

1. Coverage-guided constrained sampling replaces the lattice walk; the lattice remains
   available as a deterministic fallback so behaviour degrades rather than failing.
2. Extend beyond the six knobs the lattice touches, using manifest-legal values only.
3. Emit multi-shape family-sweep candidates so a mutant can be graded (`Hplan.1` item 5).
4. Re-derive `ThreadTile`/`WorkGroup` from `MacroTile` the way `_reconcile_knobs` does, so
   the product constraint holds by construction.

**Status: landed.** `synthesis.py`; 79 tests in `tests/test_synthesis_phase4.py`. Notable
decisions, and what forced them:

- **Item 2 was already satisfied by Phase 2, and the knob budget is exhausted.**
  `legality.KNOB_GROUPS` covers all eight structural knobs the shipped solutions encode
  (`MacroTile`, `ThreadTile`, `WorkGroup`, `VectorWidth`, `GlobalLoadVectorWidthA/B`,
  `GlobalSplitU`, `DepthU`), plus `af0em` riding with the split group. The one remaining
  parsed knob, `grvw`, is deliberately excluded: it is not a Tensile parameter, and
  `BenchmarkStructs` calls `printExit()` on unrecognised names. So "extend beyond the
  lattice's six" is met by covering every legal knob, not by inventing parameters.
- **`TEMPLATE_KEYS` moved to `legality.py`** and is re-exported by `mutator.py`. It was
  defined in `mutator`, but it names the keys `legality` *assembles*, so the definition
  belongs with the module that produces them; two copies would be two answers to one
  question.
- **The band is resolved lazily via `ConvergenceAgent.band()`, never in `__init__`.**
  `ab_audit.arm_record_sets` constructs an agent to manage phases, and
  `coverage.measured_band_pct` calls `arm_record_sets` — so computing the band at
  construction time is a cycle that ends by exhausting the stack. It was caught by
  `TestMeasuredBand` hanging rather than failing; `BandResolutionTests` now pins it. Note
  that a band of 5.0 on an empty corpus is `TIE_BAND_PCT`, the documented shipped floor,
  not an invented measurement.
- **The ledger's single `shape` column keeps the cell identity; the sweep goes in phase
  data.** Coverage joins on `(family, shape)`, so recording the sweep's first shape would
  re-file the candidate into a different cell and make the coverage joins wrong.
- **`retired` cells are skipped, not sampled.** Every candidate in such a cell was
  non-functional; re-drawing the neighbourhood is what the negative cache exists to stop.
- **Two latent bugs were found by the new tests and fixed.** `reconcile_tile` returned
  early on a *missing* `ThreadTile`/`WorkGroup` — the exact case it exists to solve — and
  an unsolved dimension rendered as the literal string `"None"`, which Tensile would
  reject at parameter-parse time rather than at our own check.
- **The lattice fallback is reported, never silent.** A run that quietly falls back looks
  identical to one that did not. `last_emission_stats` now carries `retired_cells`,
  `lattice_fallback_cells`, `ungraded_cells`, `graded_cells`, and `band_pct`.
- **`DepthU` travels with the tile, and crossing pairs are pruned against the shipped
  manifest.** The shipped manifest stores DepthU as the K component of the MacroTile —
  Tensile's `128x32x16` *is* "MacroTile 128x32 at DepthU 16" — so moving DepthU on its own
  manufactured exactly the occupancy rejections the scheduler's model then misread (16 of
  24 HS_HPA rejects in the first legality measurement). `DepthU` now rides with the `tile`
  group (`KNOB_GROUPS` is `tile`/`split`), and every emitted candidate's *cross-group* knob
  pairs are required to co-occur in some shipped solution (`legality.cooccurrence_check`,
  cached per family). This is co-occurrence read off the manifest, deliberately not a model
  of the reject set — the occupancy/assembly predicates still reject configs Tensile
  genuinely ships (verified: 31/135 shipped HS_HPA, 19/169 SS), which is why they are *not*
  hard walls. Measured consequence: the Phase-4 legal rate went 88% (176/200, HS_HPA 0%,
  HH_HPA declining entirely) to **100% (232/232) with all seven families proposing and zero
  false drops** (`/tmp/opencode/legality_p4.py`). The gate alone cannot reject a config
  Tensile ships — a shipped solution co-occurs with itself.

### Hplan.7 Acceptance criteria

The thirteen criteria in `proposal.md` §H.7 are the authority and are load-bearing: each
names the test that fails if its section is reverted. Three deserve emphasis here because
they pin the plan's own claims rather than the design's:

- the outcome classifier is validated against the **archived** mutant directories plus a
  same-run control population, not a hand-written example;
- the negative cache is replayed against a historical subspace that spent a large number of
  records at zero yield, and must emit nothing from it after *k* consecutive failures;
- structural legality is asserted **without** calling `validate_config`, so the sampler
  cannot pass by leaning on the assertion it is supposed to precede.

### Hplan.8 Sequencing and PoC gates

Every phase is CPU-testable; **none requires GPU time**, and none may be validated by
running Tensile (`claude.md` §5: full benchmarks are TTY-and-user-only). Each module is
PoC'd in `/tmp/opencode/` before it lands, and no change lands without a PoC plus a scoped
parity check. Phase order is Phase 1 → 2 → 3 → 4; see `proposal.md` §H.9 for why that order.

### Hplan.9 Exit criteria

- [ ] `proposals` ledger exists, survives a registry flush on a DB copy, and never loses a
      row to a retention or rebuild operation.
- [ ] Two consecutive simulated iterations emit zero duplicate `fp`.
- [ ] Outcome classification reproduces the archived mutant population exactly, with a
      control population at the expected yield.
- [x] Legal rate of emitted candidates ≥ the bar in `proposal.md` §H.7, measured live.
      100% (232/232) across all 29 deck cells, all 7 families proposing, measured with
      `band=None` against the live registry (`/tmp/opencode/legality_p4.py`); the bar is
      95%. The mid-phase 88% reading (HS_HPA 0%, HH_HPA declining) was the pre-gate sampler
      crossing `DepthU`/`GlobalSplitU` onto incompatible tiles; see Hplan.6 for the fix.
- [x] `phases.yaml` byte-identical across an `--auto` run. Candidates are written to the
      per-run overlay by `mutator.write_overlay`; `mutate_and_feed`'s only `phases.yaml`
      path is the pre-Phase-1 no-mutator fallback, which is not the configured path
      (`port_tensile.py` constructs a `Mutator`).
- [ ] Every proposal row carries `origin`, non-null `parent_fp`, and a resolved `outcome`.
- [ ] `ab_audit.py` reports `n`, spread, and the origin split.
- [ ] No corpus count transcribed into code, comment, or test.
- [ ] Full `tests/` suite green; the `--auto` no-mutation path (see below) still works.

### Hplan.10 Known gap found while formalising — `--auto` cannot currently disable mutation

Recorded here because it blocks the "no mutations" run requested alongside this plan, and
because it is defect 1 of `Hplan.1` seen from the CLI.

Today **no flag turns mutation off**:

- `--mutation-budget 0` does **not** disable it. `scheduler.mutate_winner` emits
  single-knob mutants unconditionally; the budget only gates the two-knob block
  (`scheduler.py:379`). Zero yields a one-knob sweep, not no sweep.
- `--budget 1` does **not** avoid it either. The loop body runs the manifest, then
  evaluates convergence, then calls `mutate_and_feed` (`agent.py:400`) — and only
  *then* increments the iteration counter and re-tests the budget. So a single-iteration
  `--auto` still harvests and mutates. (Since Phase 1 the candidates go to the per-run
  overlay, not `phases.yaml` — the original "polluting the curated deck" wording predates
  that and no longer applies.)
- `--stage` gates only the non-`--auto` branch (`port_tensile.py:3195`); it does not
  constrain `run_auto`.

The safe mutation-free path today is to **omit `--auto` entirely** and run the plain
Stage-3 path (`--stage 3`, or any of the `--family`/`--shape`/`--pattern` selectors),
which executes the deck once, updates run status, and regenerates the acceptance report
without entering the harvest/mutate loop. That is what `command.txt` now contains.

**Resolution (2026-10-05, user): withdrawn, not deferred.** Omitting `--auto` and using
the plain Stage-3 path is the intended and only mutation-free route, so there is no need
to give `--mutation-budget 0` the meaning "emit nothing" and no need to re-gate
`mutate_and_feed` on remaining budget. Those two behavioural changes are **not** planned
and no longer await approval. The defect that remains real is the one below, and Option H
addresses it at the source instead of via a flag.

The substantive gap Option H actually inherits: `--auto`'s only control over mutation
*width* is a flag whose help text overpromises. `mutate_winner`'s ≤2-knob lattice is
replaced by the manifest-legal sampler under `Hplan.6`, which bounds the search by
construction instead of by a flag that does not bound anything. `--mutation-budget` is
retained for compatibility and is expected to keep its current effective meaning (a
lower bound of 1 on knobs touched) until `Hplan.6` lands.

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
- [ ] **Option H decision recorded** — approved at a stated phase boundary, or rejected
      with the rejection and its reason in `proposal.md` §H.10. Approval of this plan's
      §Option H is a separate decision from approving the design.

## Relevant Files
- `implementation_plan.md` (this plan — self-contained), `gfx90c_theoretical_limits.md`
  (ceiling authority), `mapping.md` (footprint contract), `potential_configs.md`
  (candidate deck), `changelog.md` (evolution), `results.md` (data, append-only),
  `claude.md` (entry contract), `knowledge_base.md` (data law §10), `proposal.md`
  (measurement-protocol history + the Option H mutator design; its §Option H addendum is
  the evidence and rationale behind this file's §Option H plan — the two are not
  interchangeable and neither duplicates the other).
- `command.txt` — the current user-run invocation (native deck, single iteration,
  no mutations). Its header records why `--auto` cannot express that today
  (§Option H, `Hplan.10`).
- Live repo: `gfx90c_common.py`, `tensile_library.py` (gfx900 dat parse + reference
  chain), `report.py` (writes `gfx90c_results/acceptance_report.json/.html`), the
  native gfx90c patch (`Tensile/Common.py` + `Tensile/AsmCaps.py`, in the Tensile
  tree), `gfx90c_results/registry.db`, `gfx90c_runs/` (`gfx900_ref_*` + `run_*`).
- Sanctioned prior conclusions: `prior_INSIGHTS_CAVEMAN_ULTRA.md`,
  `prior_RESEARCH_ARCHIVE.md`.