# gfx90c — oto Implementation Plan (One-Shot Deterministic Convergence)

> Status: **APPROVED-IN-PRINCIPLE**. Native port mechanics are proven (frozen
> baseline: parity at 0/11/0 same-run; the gap is coverage + beating
> the spoof floor). oto contract: **beat the gfx900 spoof baseline across the
> entire shipped kernel suite** AND approach the gfx90c theoretical limit as closely
> as possible (limit authority = `gfx90c_theoretical_limits.md`, cross-checked
> against rocminfo + first-party sources). Ruthless simplicity; deterministic; NO LLM
> in the loop. Read it top-to-bottom before implementing; the stage/design detail
> and the triaged-fix disposition are archived in `changelog.md` (2026-10-12).

## Objective

Beat the gfx900-spoof floor across the whole shipped gfx90c footprint and
approach the per-family ceilings as closely as the machine allows. The goal and
the standing success bar are stated in `tensile_tuning_context.md` (Scope); the
footprint contract is `mapping.md`; the campaign is driven by
`port_tensile.py --auto`.

## Core Strategy (one-shot deterministic convergence)

```
shipped gfx900 footprint (28 families, 4 patterns; the live phase list is
    generated and printed by `oto/tools/allruns.py`, never transcribed here)
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

See `tensile_tuning_context.md`. The model proposes parameter vectors only;
Tensile generates, the compiler validates, the hardware decides.

## Correctness Gate

Always generate → correctness → benchmark; never benchmark → fast →
maybe correct. The rejected-config list and the routing rule are in
`tensile_tuning_context.md`.

## Reward Hacking

Independent benchmark + fresh inputs + correctness + repeats + guard checks;
evaluator outside model control; median-of-seeds, never max-of-seeds. See
`tensile_tuning_context.md`.

## Manual-LLM Contingency

User-invoked, add-only, worst case only. A single canned prompt producing ≤5 candidate
recipe mutations, dumped into `phases.yaml`, flows through the same deterministic pipeline.
Never an in-loop consultation.

## Important Details (verified current state)

### A. Frozen baseline (rules; run history in `changelog.md`)
- Port mechanics **DONE**: pristine Tensile + minimal in-tree gfx90c support;
  Phase-0 gates 10/10 [OK]; anti-alias 0 gfx900 leak; synthesis PASS.
- Performance on the only frozen same-run pair = **parity, not wins** (0 / 11 / 0
  at ±5%); candidate suite A–G = **5W/10T/6L** over 21 shared cells. These are
  the carried ceiling bars in `results.md`, not current verdicts.

### B. The replicated footprint (mapping contract)
**2,285 distinct shipped kernels.** The family matrix, the size-key count, and
the "do not chase the defensive size mesh" rule are all owned by `mapping.md`.

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
  controls reported, never inferred (`oto/device/peaks.py`).
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

#### GCN5 GEMM literature review folded into its owners (2026-10-19)
- `gfx90c_gcn5_gemm_literature_caveman_full.md` (a `/caveman full` external
  literature pass) was integrated section-by-section and retired: mechanisms →
  `kernel_tuning_research.md` (§1 no packed-FP32 FMA; §3.4 rasterisation vs wave
  quantisation + the CPU predictor; §4 pipeline/cache knobs; §5 the Higham 3M
  caveat + non-atomic split-K; §8.7 split-K/Stream-K/persistent; §9 do-not-cite);
  complex/FP64 → `complex_gemm_research_brief.md` (§5 Higham; §8 register blocking
  + the packed-FP32 correction; §9 non-atomic split-K; new §11 complex-double
  occupancy/ILP); search design + measurement → `tensile_tuning_context.md` §S and
  `knowledge_base.md` §8.3; tile-shape provenance → `gfx90c_tuning_guide.md` §1.2;
  the roofline closed form → `gfx90c_theoretical_limits.md` §3; and the ranked
  experiment order → `potential_configs.md` §R33 (mapped onto the existing routes;
  its steps 4 and 7 are *not* reachable as candidates on this port). No new routes;
  the review's `[CHECK]`/`[Transfer only]` labels are preserved.

#### The 14 residual literature questions folded (2026-10-19)
- `gfx90c_gcn5_gemm_residual_14q_caveman_full.md` (the `/caveman full` answer pass
  over the questions the review left open) was integrated and retired. Each verdict
  is closest-evidence-found and none is gfx90c-specific: Origami + the predictor and
  the 2025 irregular-batched-GEMM work in `kernel_tuning_research.md` §3.4; the MI250X
  non-temporal experiment and the Tensile `StaggerU` scoping in §4; the
  `GlobalSplitUAtomicAdd`/`StreamK`/`StreamKAtomic` knob names in §8.7; the LLVM
  GFX6–GFX9 VGPR-allocation rule in §9.3; oneMKL's `gemm3m` error bounds in
  `complex_gemm_research_brief.md` §5; AMD measurement methodology in
  `knowledge_base.md` §8.3; and a closing note in `potential_configs.md` §R33. The
  pass **changes no route** and adds no module.

#### Legality gate closed + tile ceilings (2026-10-18)
- The gate census is now **0 MISS / 0 FALSE REJECTION** (3349 configs, 3217
  built, 132 empty; was 79 refused + **53 MISS**) from three calibrated rules:
  the workgroup register file (`R*MT0*MT1*LocalSplitU >= 65536`, Tensile error 4;
  ThreadTile cancels, so it caps MacroTile *area*), the LSU LDS reduction
  (`LSU*MT0*MT1*computeBytes > 65536`, Tensile `MaxLDS`), and a generator-seam
  refusal of `AggressivePerfMode ∉ {0,1}`. The reference population keeps its
  documented 43 false rejections (all the pre-existing LDS tile-footprint proxy
  on large-DepthU gfx900 kernels), a reference-only story. Each new rule adds 0
  false rejections to both populations.
- The tile axes now have **provable ceilings**: area `< 65536/R` (SS/HH 65536,
  DD 32768, CC 16384, ZZ 8192). A brute force above CC 8192 / ZZ 4096 finds none
  legal, so the widest legal complex tiles are CC `128x64` and ZZ
  `64x64`/`128x32`; `potential_configs.md` §8.2's "legal but never generated"
  headroom list is retired as wrong.
- The same dead wide tiles lived in **three** homes and are all repaired
  (`phases.yaml` 4 rows, `decks.FAMILY_DECKS`, `candidate_rows.LADDER` +
  `PLAN_BATCH`). `check_candidates.py --quiet` is **284 rows, 0 illegal**;
  `TestEveryDeckRowIsGenerative` pins that no deck/ladder/batch row is
  gate-refused under any contraction pattern. Candidate pool 405 → 416.
- Live report `run_20261018_004835` reads **20 WIN / 18 TIE / 0 LOSS** (0 RED /
  12 ORANGE, **PROVISIONAL** floor): `CC:256` moved **TIE → WIN (+7.8 %)**, the
  R8 steal landing. (The 12 ORANGE were re-scored on 2026-10-21: ten of them
  were a 4x unit error in the complex bar, and the list is **three** cells --
  `results.md` §16.) Evidence `results.md` §14; reading `potential_configs.md`
  §R24–§R32 (rewrite 6).
- The rule-calibration machinery behind those three rules is now a repo tool,
  **`oto.harness.rule_calibration`**: it probes any candidate
  `config -> Optional[bool]` predicate against the corpus and reports the false
  rejections (must be 0) and empty-phase catches. `builtin_rules` re-verifies the
  shipped rules as *views* of the gate and keeps the **rejected** `nt_budget`
  candidate (`min(256, 65536//NumThreads)`, 1 false rejection) as the worked
  counter-example; `--rule module:attr` probes a rule that is not in the gate yet.

#### CC:256 loser resolved — candidate sweep-order bug (2026-10-15)
- The last LOSS cell (CC:256) was a producer bug, not a kernel deficit:
  `oto/harness/candidate_pool.py` sorted `ProblemSizes` as strings →
  lexicographic `1024,192,2048,256,512`, so 256³ was measured immediately after
  the 2048³ kernel at ~⅓ clock. Fixed with a numeric shape key at every sort
  site; module "Owns" note updated.
- Bug was generator-wide: **366/367** generated candidate rows carried the
  scrambled order (every lexicographic-order corpus phase is a candidate-pool
  phase). Ordering now lives once in `oto.tensile.shape_order` and is applied at
  all three producer sites (wide-row build, existing-row merge, and
  `_narrow_row_gen`'s in-place merge), with a last-mile guard in
  `config_writer.write_phase_config` that re-imposes it regardless of producer
  input. Pinned by `tests/test_generate_candidates.py` and the new
  `tests/test_shape_order.py`; the live seed overlay was regenerated numeric.
- Live report `run_20261015_041159` reads **19 WIN / 19 TIE / 0 LOSS**;
  CC:256 **TIE**. No verdict band or gate logic changed. See `changelog.md`
  2026-10-15 and `results.md` §13.4.

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
  only in per-run `logs/telemetry.csv`. `oto/metrics/telemetry.py` samples at 10 Hz with a
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
### HS_HPA assembly guard (rule)
The HS_HPA rejection is stock Tensile's non-MI `GLVW == VW-or-1` generator guard
(triggered by the pv-reduction in `setGlobalLoadVectorWidth`) — isa-independent,
**not** a gfx90c HW/ISA limit and not an assembler failure. Guard-legal HS_HPA
parameterizations are admitted and assemble for gfx90c; `_validate_tensile_loads`
mirrors the predicate.

---

## The Driver Architecture

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

### 4. Reference-floor contract (unchanged)
The spoof floor is the **dedicated `gfx900_ref_*` run chain**: benchmarked once per
shipped kernel (`--gfx900-reference`), continued via `--resume` when interrupted, then
recalled — never re-rolled — by every acceptance report. It is a **floor, never a
retirement signal**.

### 6. Migration order (don't rewrite blind)
1. `oto/ledger/registry.py` + `oto/metrics/report.py` extracted, unit-tested, still fed by the existing
   data layout.
2. `phases.yaml` transcribed (mechanical).
3. `oto/metrics/policy.py` + `scheduler.py` extracted; gate-matrix re-run.
4. `port_tensile.py` takes over phase-by-phase-group; `--targets` scoping parity
   checked against the reference-floor chain.
5. Agent loop + `--auto`; convergence budget configurable.
6. Single entrypoint: the python driver.

---

## Option H — acceptance and exit criteria

> Option H's design, evidence and the four landed phases are archived in
> `changelog.md`; the code contracts live in the `oto/ledger/*` and
> `oto/tensile/synthesis/*` docstrings. These two sections are the live gates.

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

### Hplan.9 Exit criteria

- [x] `proposals` ledger exists, survives a registry flush on a DB copy, and never loses a
      row to a retention or rebuild operation. — `tests/test_ledger_durability.py` drives the
      real threats (WAL checkpoint, VACUUM rebuild, copy-then-reopen) against real SQLite and
      asserts the guarantee, never a transcribed count.
- [x] Two consecutive simulated iterations emit zero duplicate `fp`. —
      `tests/test_mutation_arm.py` (two-iteration disjointness; replaying one iteration
      suppresses every candidate via novelty, and `last_emission_stats["rejected_non_novel"]`
      counts the rejects).
- [x] Outcome classification reproduces the archived mutant population exactly, with a
      control population at the expected yield. — `tests/test_mutator.py` +
      `tests/test_phase1_integration.py` replay the archived mutant directories through the
      classifier and assert nothing non-functional is misread (every measured row is
      non-zero); the negative cache must **not** fire on it.
- [x] Legal rate of emitted candidates ≥ the bar in `proposal.md` §H.7, measured live.
      100% (232/232) across all 29 deck cells, all 7 families proposing, measured with
      `band=None` against the live registry (`/tmp/opencode/legality_p4.py`); the bar is
      95%. The mid-phase 88% reading (HS_HPA 0%, HH_HPA declining) was the pre-gate sampler
      crossing `DepthU`/`GlobalSplitU` onto incompatible tiles; see Hplan.6 for the fix.
- [x] `phases.yaml` byte-identical across an `--auto` run. Candidates are written to the
      per-run overlay by `mutator.write_overlay`; `mutate_and_feed`'s only `phases.yaml`
      path is the pre-Phase-1 no-mutator fallback, which is not the configured path
      (`port_tensile.py` constructs a `Mutator`).
- [x] Every proposal row carries `origin`, `run_id`, and a resolved `outcome`; `parent_fp`
      is non-null wherever a parent exists. The one deliberate exception: an exploration
      draw in a cell with *no measured candidate at all* has no parent
      (`coverage.py` `row["parent_fp"] = parent["fp"] if parent else None`), which is the
      empty-cell case H.3.3 exists to route to exploration — annotating it, not hiding it.
- [x] `ab_audit.py` reports `n`, spread, and the origin split. — `ab_audit.py`
      `print_coverage_report` renders per-cell `n_fp`/`min_n`, `max_spread_ratio`, state,
      parent, and the `novel`/`replicate` split from the ledger.
- [x] No corpus count transcribed into code, comment, or test. — `tests/test_mutation_arm.py`
      `test_no_corpus_counts_in_executable_code` scans executable lines for the corpus-size
      literals held live by `auto_prompt._read_counts()`, and `tests/test_auto_prompt.py`
      pins the prompt source to the same rule.
- [x] Full `tests/` suite green; the `--auto` no-mutation path (see below) still works. —
      whole suite runs green at 666 passed / 1 skipped / 27 subtests (2026-10-09,
      re-verified this session).

---

## Next Move — Steps 1–6

### Step 1 — Approve + build the driver (`port_tensile.py`), per the architecture above
- Python driver + `phases.yaml` data-only manifest. `oto/metrics/policy.py` `should_run(phase,fp)`
  encodes tier-1 → tier-2 → phase-1-first-only → identical-fp skip. All evidence
  writes via `json.dumps` + SQLite `records` INSERT. `--auto` loops
  run→report→harvest→mutate. Harvest **appends `phases.yaml`**, never a DB-only
  manifest.
- **Do-not-reinvent + PoC gate**: argparse, stdlib `json`/`csv`/`statistics`/`sqlite3`,
  git for diffs, sysfs for monitoring, `PEAK_GFLOPS` imported from `oto/device/peaks.py`,
  ceilings imported from `gfx90c_theoretical_limits.md`. **Every module is PoC'd and
  fully functional in `/tmp/opencode/` before it lands.** No change lands without a PoC
  + a scoped parity run. `/tmp/opencode` currently contains analysis scratch
  (`an*.py`, pickle datasets, `poc_cellkey`/`poc_resume`) plus a pre-resume A/B dump —
  see `changelog.md` (2026-10-12). Do not land that tree as-is.

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
- `oto/ledger/agent.py` harvests per-cell winners (median-of-seeds, ruler-adjusted) → for RED or
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
      `oto/metrics/report.py` pipeline writes).
- [ ] Peak-table prose corrected everywhere to single-rate 1613 for BF16/INT8.
- [ ] Final synthesis + zero-leak anti-alias + whole-library native-vs-spoof readout.
- [x] **Option H decision recorded** — **APPROVED 2026-10-09** (§H.10 answered in
      full; see `changelog.md` 2026-10-12). Approval of the design and the
      go-ahead for the mutation arm were the same call this time.

## Relevant Files
- `implementation_plan.md` (this plan), `gfx90c_theoretical_limits.md`
  (ceiling authority), `mapping.md` (footprint contract), `potential_configs.md`
  (candidate deck), `changelog.md` (evolution), `results.md` (data, append-only),
  `claude.md` (entry contract), `knowledge_base.md` (data law §10), `proposal.md`
  (measurement-protocol history + the Option H mutator design; its §Option H addendum is
  the evidence and rationale behind the archived Option H plan, now in
  `changelog.md`).
- `command.txt` — the current user-run invocation (native deck, single iteration,
  no mutations). Its header records why `--auto` cannot express that today
  (archived: `changelog.md` 2026-10-12).
- Live repo: `oto/device/peaks.py`, `oto/tensile/library.py` (gfx900 dat parse + reference
  chain), `oto/metrics/report.py` (writes `gfx90c_results/acceptance_report.json/.html`), the
  native gfx90c patch (`Tensile/Common.py` + `Tensile/AsmCaps.py`, in the Tensile
  tree), `gfx90c_results/registry.db`, `gfx90c_runs/` (`gfx900_ref_*` + `run_*`).
- Sanctioned prior conclusions: `prior_INSIGHTS_CAVEMAN_ULTRA.md`,
  `prior_RESEARCH_ARCHIVE.md`.