# Changelog — Tensile gfx90c port

The SINGLE changelog/evolution log for the project. One fact, one canonical home:
milestone + rationale entries land here; they are never re-created elsewhere.
Prior-campaign conclusions are sourced (never copied) from the two sanctioned
prior MDs: `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

This file records project milestones and the prior-campaign → attempt2 evolution
narrative, NOT the active implementation state (that is `implementation_plan.md`)
and NOT the experimental data (that is `results.md`).

## [Acceptance best-vs-best default + telemetry-adjusted bases] 2026-09-27

- **All-zero acceptance report FIXED (arm-scope asymmetry).** The spoof arm resolved
  across the whole gfx900 reference chain (1,881 completed cells) while the native arm
  read only the reported run. `run_20260926_201835` executed 8 non-duplicate phases
  (402 were `identical_fp_already_passed`) and all 8 died on
  `Generating kernel source resulted in error 4` = `overflowedResources == 4` =
  **Occupancy limit** in the ZZ/double assembly writer → 0 native cells → every family
  `measured_cells=0`, `per_cell_verdicts=[]`, all 38 deck cells RED/MISSING at 0.0.
  The zeros were deterministic, not random.
- **Native arm is now whole-db.** `port_tensile._native_records_all_runs()` aggregates
  every `gfx90c_runs/run_*` dir's CSVs plus every registry `benchmark_result` row
  (deduped on phase/fingerprint/GFLOPS), each stamped with `source_run`;
  `_native_analytics_all_runs()` does the same for coverage/RED/ORANGE. Winners —
  including prior older winner runs — are picked across all history, matching how the
  spoof arm already worked. `gfx900_ref_*` is never admitted as native.
- **Delta-semantics bug FIXED (columns did not reconcile with the percentage).**
  `delta_pct` was computed from the cell's **max raw sample** on both arms while the
  report's "Best native median" / "Spoof median" columns displayed **medians**, so the
  displayed ratio never matched the printed delta (CC 192: displayed 31.4 vs 31.5 =
  −0.3%, reported −6.1% from underlying 40.49 vs 43.12). All statistics are now
  **per-kernel-median-first** so one lucky seed cannot decide a verdict, and the
  default `best_median` is exactly `native_best_median / spoof_median - 1` — the deck
  winner's per-kernel median vs the floor's median of per-kernel medians, term for
  term with the two displayed columns.
- **Kernel medians are keyed by source run.** The same `(phase_id, fingerprint)`
  benchmarked by two runs was pooled into a single "kernel median", averaging across
  runs; it is now one median per (run, phase, fingerprint).
- **Rendered columns can no longer disagree with the delta (second delta bug).** The
  two A/B columns were hard-wired to "Best native median" / "Spoof median" regardless of
  the basis in use, so switching basis silently re-broke the guarantee fixed above. They
  now render `native_value` / `spoof_value` — the operands actually divided — under
  basis-aware headers (`report._BASIS_HEADERS`). Verified 0 mismatches in JSON and in all
  38 HTML rows (residual ≤0.44pp = 1-decimal display rounding).
- **Default comparison basis is now `winner` = BEST vs BEST** (both arms' best
  per-kernel median), the drop-in-replacement question: replacing shipped kernel X with
  native X' compares the two arms' best candidates. `winner_clock` / `median_clock` add
  telemetry adjustment; `floor_best`, `strict`, `best_median`, `median`, `throttle`,
  `best` remain selectable. All statistics are per-kernel-median-first, so "best" means
  the best *kernel* over its seeds, never the single luckiest seed.
- **Telemetry-adjusted bases implemented and independently verified.** Each kernel's
  median is scaled by `sclk_ref / sclk_measured` from its own phase's sustained clock,
  with ONE shared corpus-wide `sclk_ref` (1800 MHz) so neither arm is rescaled in its
  own favour. Per-phase clock comes from `logs/telemetry.csv` (busy-filtered median,
  >= 3 samples, idle floor excluded). Verified against an independent recompute from the
  raw benchmark CSVs + telemetry: 38/38 cells match on both the raw best and its
  normalized twin.
- **Two guards stop the clock adjustment from producing confident nonsense.**
  (1) A phase whose only busy samples sit at the 400 MHz idle clock is dropped, not
  scaled — scaling it 4.5x let a 20.7 GFLOPS kernel "win" a cell at 93.0 GFLOPS;
  genuinely throttled phases (0.9-1.2 GHz) are kept. (2) `CLOCK_MIN_COVERAGE = 0.5`
  gate, applied SYMMETRICALLY: a clock-adjusted best is only comparable if drawn from
  the same population as the unadjusted best, and at 9% coverage (CC cells) the eligible
  subset's max sat 52-67% low, flipping CC to native wins. Below the gate both arms fall
  back together to the unadjusted twin (`winner_clock` -> `winner`) and report
  `clock_adjusted: false`.
- **The native arm has no clock data, so `*_clock` is honestly inert today.**
  `run_20260919_213727` (4,896 of 6,790 native records) has no telemetry file;
  `run_20260920_235815` has 458 all-idle rows and predates `phase_id` tagging. Native
  clock coverage is 0.000 on all 38 cells, so every `*_clock` run degrades to its
  unadjusted twin with a printed warning. The spoof arm is well covered (mean 0.74,
  1,719 tagged phases), so the machinery is real but cannot be applied symmetrically
  until native is re-benchmarked with the phase-tagging sampler. Adjusting only the
  spoof arm would deflate the floor and flatter the deck.
- **Winner provenance in the report.** `analytics.compute_native_vs_spoof_delta` now
  reports `native_winner_run`/`native_winner_phase`/`native_runs`/`n_native_runs` per
  cell; `ABVerdict` + the JSON/HTML carry them, and the HTML provenance line states the
  native arm scope. An empty native arm now prints a loud warning and the summary says
  so, instead of rendering a clean-looking all-zero grid.
- **Measured result on the new default (best vs best): 14 WIN / 10 TIE / 14 LOSS.**
  Native arm = 6,790 cells from 2 runs (`run_20260919_213727`, `run_20260920_235815`);
  coverage **100% of deck cells in all 7 families** (was 0%), **0 RED / 13 ORANGE /
  25 GREEN**. Losses are modest and cluster at large shapes (HH:4096 −14.5%,
  HH:2048 −14.6%, SS:2048 −15.1%); wins are large (HH:256 +272%, SS:256 +227%,
  HH_HPA:512 +188%) but are partly a pool-size artifact, since the floor's best is a max
  over ~303 kernels/cell vs the deck's ~75. On stricter bases the deck fares worse:
  `floor_best` 3/7/28, `strict` (per-cell dominance) **0/0/38**, `median` 23/7/8.
  `overall_pass=False`.
  **Caveat:** the basis is pool-size biased against the deck — the floor averages 303
  candidate kernels per cell vs the deck's 75 (larger in 35/38 cells), so a `max` over
  the floor is biased upward. Part of the 28 losses is that asymmetry, not kernel
  quality. The decisive artifact remains a per-fingerprint pairing (native X' vs shipped
  X), which per-cell rollups cannot express. Per-cell numbers in `results.md` §10.
- **Reference floor chain complete.** `gfx900_ref_20260926_201843_resume`: 1,212
  targeted, 808 completed, 404 failed → chain **1,881 completed / 404 unique failed =
  2,285 decided, 0 undecided**. 116 base failures retried and failed again; 288 new.
- **Open (not fixed here).** `_write_phase_config` still returns early on the
  assembly-class gate without writing the config, so `execute_phase` launches Tensile
  against a missing path — the 121 rc=1 bucket. Reference-deck generation should
  pre-filter those configs. Tracked in `implementation_plan.md`.

## [Named workload cells + reference-floor A/B fix + HPA case-sensitivity] 2026-09-26

- **A/B floor binding bug FIXED (`ccd7fed`).** `port_tensile.py` `_compute_ab_verdicts`
  bound the spoof floor from the wrong tuple slot (`ref_records, _ = _ab_records_from_csv(
  ref_dir, force_arm="spoof")` puts all records in the second element), silently dropping
  the floor → "0 WIN / 0 TIE / 0 LOSS" reports. Corrected; the same run now yields
  **30 per-cell verdicts (18 WIN / 9 TIE / 3 LOSS)**.
- **Workload-cell naming (fix.md applied, `ccd7fed`).** Every measured row is stamped
  `arm` + `cell_key` (`"<FAMILY>:<SHAPE>"`) + `kernel_key` via `gfx90c_common`
  `cell_key()`/`kernel_key()`/`shape_side()`; `analytics.compute_native_vs_spoof_delta`
  now pairs by workload cell `(family, dtype, shape)` on BOTH arms (best-of-cell median,
  ±5% tie) instead of spoof-per-fingerprint vs native-per-cell.
- **Live DB stamped (`ccd7fed`).** `gfx90c_results/registry.db` backfilled — 3,369
  measured rows carry `cell_key`/`arm`/`kernel_key`; pre-backfill backup at
  `backups/2026-09-26_impl/registry.db`. Added `idx_cell_key` index — NOTE:
  `registry.py` does not create it, so a fresh DB lacks the index.
- **HPA case-sensitivity FIXED (`58245c8`).** `_write_phase_config` matched
  `"HPA"/"HS_HPA"` case-sensitively, so lowercase agent mutants (`mutate_hh_hpa_…`,
  `mutate_hs_hpa_…`) ran as plain FP16 without `HighPrecisionAccumulate`/
  `DestDataType`. Now uppercases + consults `FamilyLabel` (consistent with
  `assembly_class_valid`); `agent.mutate_and_feed` stamps `FamilyLabel` on mutants.
  Verified against all 6 label shapes (deck / reference / mutant). Closes the
  round-2 HS_HPA pending item: HS_HPA 16 cells run at MT64x64x16 with the
  `GLVW==VW-or-1` mirror predicate.
- **Analytics cleanup (`58245c8`).** `analytics.py` dropped unused
  `cell_key`/`kernel_key` imports.
- **Corrections to earlier entries (append-only).** The "Shim removed:" bullet's
  "deleted" claim is technically inaccurate — `tensile_gfx90c_port/` source is gone
  from git, but shim-era `__pycache__` `.pyc` residue remains on disk (untracked;
  scheduled for cleanup). The bottom "Upstream baseline" section's "pristine HEAD,
  shim-only" wording is fully superseded by the native 2-file `Common.py` +
  `AsmCaps.py` patch entry.

## [Graceful gfx900-reference resume + completeness gate] 2026-09-26

- **Reference runs are now resumable.** `tensile_library.reference_chain()`
  returns the newest completed, non-smoke `gfx900_ref_*` run plus its
  `resume_of` ancestors as one logical floor; `port_tensile` `--gfx900-reference
  --resume` creates `gfx900_ref_<ts>_resume` targeting ONLY the base deck's
  phases with no completed verdict (unattempted + failed-again once), reusing
  the completed base phases as-is (`_chain_phase_sets()` distinguishes
  completed vs decided). A/B verdicts (`_compute_ab_verdicts`) and family
  timings now recall the WHOLE chain, not the newest run alone, so cells split
  across base and resume are never lost.
- **`--auto` completeness gate.** If a completed reference run exists but the
  deck has undecided phases, `run_auto` now resumes it first and refuses to
  proceed with ANY tuning until `_reference_remaining() == 0` (every shipped
  phase has a verdict — completed, or enumerated-invalid `failed`). Previously
  a truncated (47%) run was silently recalled as the floor and the remaining
  ~1096 phases were permanently dropped. `--gfx900-reference --resume` alone
  returns `noop` when the deck is already complete.

## [Run-wide telemetry + gpu_busy_percent path + peak-table reconciliation] 2026-09-25

- **Telemetry is now run-wide, not per-phase.** `telemetry.py` `TelemetrySampler`
  gained `set_phase()` + a `phase_id` column and a restart-safe `start()` (header
  written only when missing; never truncates). `port_tensile.TensileDriver` keeps
  one sampler per run dir via `_ensure_telemetry()`, tagging every row with the
  active phase in `execute_phase` and clearing the tag in its `finally`. Previously
  each phase created a fresh sampler whose `start()` truncated `telemetry.csv`, so
  a ~9.5h run kept only the last (~46s, itself an idle failed-at-compile ZZ phase)
  window — the root cause of "telemetry only measured for ~40 seconds".
  `run_gfx900_reference` stops the sampler on its run-dir swap. `report.py` reads
  the CSV by column name (`csv.DictReader`), so the extra column is transparent.
- **gpu_busy_percent path hardened.** Primary discovery now requires the candidate
  card dir to actually expose `gpu_busy_percent` (rejects connector dirs like
  `card1-DP-1/device`, which symlink to the card node and have no busy file); the
  `/sys/class/hwmon` fallback no longer appends `/device` (double-suffix never
  resolved → busy would always read 0 if the fallback ever fired), and a sampler
  that cannot find the busy file prints a one-time warning instead of silently
  logging zeros. The surviving run's busy=0 was *correct* data — its last phase
  failed during compilation (GPU never woke; sclk pinned 400 MHz).
- **Peak/ceiling tables reconciled** (`gfx90c_common.py` is the single authority;
  `gfx90c_theoretical_limits.md` §5 now quotes its exact values). Added the missing
  BF16 `1109` and INT8 `881` entries to `REALISTIC_CEILINGS`; §5 updates 1119→1118.7
  (SS/CC/HH_HPA/HS_HPA), ~98→98.6 (ZZ); §2.1 notes `PEAK_GFLOPS['FP64']` stores the
  rounded 101 (vs derived 100.8). Removed the stale "(replaced by …)" comment in
  `gfx90c_common.py`.

## [Shipped-dat gfx900 reference floor + red/orange cell semantics] 2026-09-25

- **New `tensile_library.py`.** Parses the system ROCm `TensileLibrary_*_gfx900.dat`
  binaries directly (msgpack length-prefixed solution names, marker-canonicalized
  `Cijk_...`), unions every installed ROCm prefix (`/usr` + `/opt/rocm`), emits one
  spoof phase per shipped kernel with its MT/WG/VW/DepthU/GSU knobs, and pins the
  result once at `gfx90c_results/gfx900_shipped_manifest.json` (pin-on-first-load,
  `refresh=True` re-scans). Live expected counts: SS 959, DD 96, HH 223, CC 64,
  ZZ 26, HH_HPA 424, HS_HPA 493 → **2,285** distinct shipped kernels (the old 3,066
  was per-file token counting). Config generation validated on all families
  (2,164/2,285 assembly-legal under the class gate).
- **One-time reference run (`--gfx900-reference`).** Benchmarks every shipped
  gfx900 kernel once (ScheduleName `vega10`, `FAMILY_SHAPES` deck) into a dedicated
  `gfx900_ref_*` run; later A/B `_compute_ab_verdicts` *recalls* it forever instead
  of re-running per-run baselines. The 8 hand-authored `*_baseline_*` phases were
  removed from `phases.yaml`; `run_auto` now just checks the reference run exists.
- **RED = MISSING, ORANGE = <50%.** `analytics.classify_cell_status` classifies each
  gfx900 contract cell `(family, deck-shape)` from `FAMILY_SHAPES` (38 cells):
  RED if unmeasured this run, ORANGE if best measured candidate is below the
  family realistic ceiling threshold, else GREEN. `report.py` gate/summary/JSON/HTML
  reworked to these semantics, with per-family coverage denominators now derived
  from the pinned manifest and the reference-run provenance embedded in the report.
- **Perf fix.** `_ab_records_from_csv` re-parsed the 9k-line `phases.yaml` per CSV
  (hundreds of parses per report); it now builds a phase-id → phase dict once
  (~120s → ~1s per report regeneration).

## [Cruft audit + convergence contract + CLI stage dispatch] 2026-09-25

- **Convergence contract fixed (`agent.converged()`).** Removed the `iteration < 10`
  bypass; budget exhaustion is now a STOP that returns `converged=False` (never
  reported as a pass), and a CV ≤ 15% per-cell stability gate was added via the new
  `CellAnalytics.cv` field. Criteria: no below-ceiling cells, ≥3 configs/cell, ≥2
  independent runs/cell.
- **Mutation family loss fixed (`agent.mutate_and_feed`).** Winners now harvest their
  `.family` token, mutation derives the Tensile DataType from `FAMILY_DTYPE_CHAR`
  instead of raw dtype char, so HH / HH_HPA / HS_HPA winners no longer silently fall
  back to FP32. Harvest/emit now carry `is_below_ceiling`; agent construction dropped
  the unused `max_iterations`/`red_threshold_pct` kwargs (driver updated).
- **Single-path retirement.** Removed dead `classify_retirement_tier`,
  `apply_d2_4_protection`, `classify_tie`, `should_repeat`, `classify_stability`
  (policy.py) and registry `append_records`/`get_run_info`/`get_latest_run_dir`/
  `has_phase_passed`; retirement is the single Tier-2 path via
  `check_retirement_eligibility` + `should_run`/`is_config_retired`.
- **`--stage 1-7` dispatch + bugs.** `create_run` now recognizes stage `"7"` (the old
  `"report" in args.stage` never matched the number, minting stray runs); read-only
  stages 2/4/5/7 no longer create runs; stages 1-5 have explicit handlers (preflight /
  candidate plan / benchmark / retirement sweep / analytics summary).
- **`--force` no longer a no-op.** Wired as `opt_in_identical_skip=False` through
  `run_auto` (flag was previously parsed but never read).
- **RED semantics rename.** `is_red` → `is_below_ceiling` (report RED = missing
  contract cell stays untouched); `Red` → `below_ceiling` in harvest/convergence.
- **Coverage metric fixed.** `_compute_family_coverage` denominator is now the
  contract deck (`FAMILY_SHAPES[family]`, coverage = deck cells measured); the
  shipped-kernel footprint moves to informational `footprint_pct` in the report.
- **Centralized maps.** `REALISTIC_CEILINGS` (SS 1118.7 / DD 98.6 / HH 2461.0 /
  ZZ 98.6 / CC 1118.7 / HH_HPA 1118.7 / HS_HPA 1118.7) and `FAMILY_DTYPE_CHAR` are
  now both canonical in `gfx90c_common.py`; `tensile_library.py`, `analytics.py`,
  `scheduler.py`, `report.py`, `agent.py` import them (family decks use
  `MAX_WAVES_PER_CU` instead of a hardcoded 40).
- **Dead code / imports / state removed.** Local unreferenced `TelemetrySampler`
  class + `termios`/`tty`/`Set`/`PEAK_GFLOPS` imports in `port_tensile.py`;
  `MANIFEST_KEY`/`expected_kernels_from_manifest` (tensile_library.py);
  `persist_analytics`, `THEORETICAL_PEAKS`/`DDR_ROOFLINE_GBPS` deps (analytics.py);
  `compute_ab_verdict`, `_family_to_dtype`/`mapping_path` (report.py);
  `classify_bound_class` (scheduler.py); orphan
  `tools/__pycache__/merge_draft_gfx90c.cpython-314.pyc`.
- **Regression caught & fixed during the audit.** `_KNOWN_FAMILIES` (analytics) lost
  its lowercasing when re-derived from `FAMILY_DTYPE_CHAR`, breaking every
  `extract_family_from_phase_id` match, and the `dtype_to_family` fallback collapsed
  the ambiguous `'H'` char to `HS_HPA`. Both fixed (lowercase prefix set; first-wins
  char map → `'H'` = HH). Regenerated report identical to baseline: `Acceptance FAIL:
  0 WIN / 0 TIE / 0 LOSS, 0 RED (missing) / 15 ORANGE (<50% ceiling)`.
- **Docs sweep.** Replaced stale 3,066 pip-count references with the live 2,285
  manifest split in `implementation_plan.md`, `knowledge_base.md`,
  `knowledge_base_final.md`, `incomplete_work.md`; updated RED-list/RED-cell
  terminology and dead-helper mechanism claims; expanded the `gfx90c_common.py`
  single-source-of-truth row.

## [Assembly-class gate + 295-phase deck + draft-merge tooling] 2026-09-20

- **Class-based Assembly gate (`scheduler.assembly_class_valid`).** Faithful to
  the Tensile SolutionStructs rejects reproduced from the 24 draft-run failures:
  GSU>1 on complex, GSU>1 on half+f32-accum (HPA), GSU>1 on half without
  `AssertFree0ElementMultiple>=2`, and `DepthU * BytesPerElement > StaggerUStride`
  (complex DU>=32) are all illegal on gfx90c (no MFMA). Wired at BOTH seams:
  `scheduler.validate_config` (mirror gate) and `port_tensile._write_phase_config`
  (autoskip — illegal cells never written to the Tensile deck). Class-based, so
  ANY future same-class cell is caught pre-run, not just the 24 triaged. The
  loky/semlock ValueError from the draft re-runs was benign stderr noise
  (joblib>=1.5.2 is cosmetic only); the 24 were solution-validity rejects.
- **331 → 295 phases.** Regenerated `phases.yaml` through the new gate: the 36
  GSU-2/4/8 cells on HH/HH_HPA/HS_HPA dropped (HH 56→40, HH_HPA 32→20,
  HS_HPA 28→20). 0 illegal cells, 0 fp/phase_id dups, 0 validate_config fails.
- **CASE3 merge tool (`tools/merge_draft_gfx90c.py`).** Append-only import of the
  draft run's 4962 benchmark records under the MAIN fp scheme (FamilyLabel-tagged;
  draft target_id fps were NOT portable). `.bak`-first on both registries, no
  dedup/deletion/id-reuse, retirement left to the codebase's 3-tier gate
  (policy.py:240). Dry-run reports exactly 2 retirement-eligible fps — the two
  A/B baselines (48 samples each, 2 independent runs); everything else needs a
  2nd shell from our deck. run2 added nothing new beyond the baseline 2nd shells
  + 6 auto SS@1024 cells (3 samples each, single run — reference only).
- **CASE3 import applied (run1 only).** `--runs run1` (default), run2 skipped per
  decision — its only value was the baseline 2nd shells, and the codebase gate
  can reach retirement later with 2 independent runs. Executed 2026-09-20: 445
  phase entries (baseline baselines_ss_native/spoof + 443 wide cells) + **4896
  benchmark records** appended from run_20260919_213727. Registers run1 in the
  `runs` table (completed). Backups: `backups/main_registry.db.bak` +
  `backups/draft_registry.db.bak` (draft DB untouched — read-only). Retirement
  gate re-run post-import: 0 forced retirements (no fp has ≥2 runs yet —
  baselines are single-run in main, eligible only after their 2nd shell).
  Note: first apply attempt had a phase-dedup bug that dropped the per-sample
  records after the 1st per phase (4896→445); fixed (dedup phases only, records
  always appended) and re-applied cleanly from pristine main DB. Backups use
  distinct `main_`/`draft_` tags (initial name collision would clobber main's .bak).
- **WIN/LOSS classification from merged run1** (`potential_configs.md` §6.2–§6.5).
  Empirical per-cell class vs our carried incumbents: **24 WIN cells** (draft
  best-median beats incumbent — hh 1024³ +99%, hh 2048³ +85%, hs_hpa 2048³ +70%,
  dd 512³ +68%, ss 1024³ +66%, cc 512³ +65% top margins) and **5 LOSS cells**
  (cc 256³ −23%, hh_hpa 1024³ −21%, ss 2048³ −17%, zz all RED ~23% of 98.6
  ceiling, ss 256³ parity). Next-run policy: WINs get a 2≥-shell then ≤2-knob
  mutations (per-cell table §6.2); LOSSes never re-run their fp — replaced by
  fresh structural candidates proposed in §6.3 (MT128/TT8/DUs/GSU-1, class-gated).
  Spend order §6.5: WIN shells → WIN mutations → new-wide-for-LOSS → GSU-1@4096 SS.
- **Next-increment proposal (`potential_configs.md` §6).** Wider-for-LOSS (CC/ZZ
  structural, HS_HPA admitted parms, SS GSU-1@4096), narrower-for-WIN (DD closed,
  SS/HH no double-spend), 2≥-shell-first spend order, strategy-scoped retirement.

## [Wide gfx90c candidate deck (331 phases) + --auto baseline-anchored one-command integration] 2026-09-20

- **Wide deck replaces the 304-phase manifest.** `phases.yaml` regenerated from
  `/tmp/opencode/gen_wide_deck.py`: 331 phases (SS 105, HH 56, DD 44, HH_HPA 32,
  CC 32, ZZ 32, HS_HPA 28, + 2 ss A/B baselines), every config passing the
  scheduler mirror (`validate_config` + `_validate_tensile_loads` GLVW guard) and
  per-shape M/N≥MT, K≥DepthU exact-size blockers — 0 invalid of 331.
  Structure: one phase per (family × contraction-pattern × config) bundling ALL
  family shapes, plus shape-matched underfill-GSU phases (small squares only, so
  GSU2/8 is not misapplied to large ALU squares) and DDR/GEMV phases.
- **fp-collision fix:** prior HH_HPA vs HS_HPA phases shared identical configs →
  identical sha256 fp → policy `has_fp_passed` identical-fp skip would drop the
  second family on re-runs. New deck keeps `FamilyLabel` (SS/HH_HPA/HS_HPA) in the
  fp input; all 331 phase_id/fp/config triples are unique.
- **Anchored `--auto`:** `run_auto` now runs Phase-0 preflight (non-fatal), then
  the spoof/native baseline A/B pair first as the anchor, then all manifest phases
  in order, then the convergent harvest/mutate loop — single overnight command.
- **A/B verdict pipeline fixed (was producing 0 verdicts):** completed/recovery
  records now carry `schedule_name`/`dtype`/`shapes`/`num_benchmarks` so arms
  resolve; `run_ab_test` now sources per-cell medians from `2_BenchmarkData` CSVs
  (which hold GFLOPS) grouped by arm instead of from registry records (which never
  carried GFLOPS). Verified with a fabricated 1:1 native/spoof cell set (WIN).
- **Accounting + telemetry fixes:** `phases_executed` counts only real executions
  (interrupted/skipped-by-user excluded) and reports `phases_skipped`; inline
  buggy sampler replaced by `telemetry.py`'s `/sys/class/drm/cardN/device`
  discovery (old `hwmon_dir.parent.parent` resolved to `/sys/class`).
- **Breaking CLI:** `--phases` removed (was an alias for `--targets`; the historic
  numeric `--phases 1 31 25` matched nothing). Use `--targets` explicitly.

## [HS_HPA fixes applied: manifest re-parameterized + scheduler mirror models the GLVW guard] 2026-09-19

- **Fix 1 (manifest):** the 16 `hs_hpa` phases in `phases.yaml` are re-parameterized
  from the rejected MT64x64x8/TT4x4/VW4 deck to the guard-legal MT64x64x16/TT4x4/VW4/
  DU16 parameterization (admitted `1/1 after SolutionStructs`, assembles for gfx90c).
  The accepted deck previously logged `Your parameters resulted in 0 valid solutions`
  on every pass (12 signalled, 0 valid); with Fix 1 all 16 `hs_hpa` cells are guard-legal.
- **Fix 2 (scheduler mirror):** `_validate_tensile_loads` (scheduler.py) now models the
  stock-Tensile non-MI assembly `GLVW==VW-or-1` predicate (`SolutionStructs.py:4583-4596`)
  that rejected the old deck — the mirror no longer pre-validates decks the guard rejects.
  Verified by 6 unit tests + a 304/304 phases.yaml sweep.
- Resolves the "Fix (pending)" bullet in the prior HS_HPA root-cause entry above.

## [Legacy-silence clauses enforced] 2026-09-19

- `claude.md` §8.1 written: removed machinery is **never** named in code or docs;
  history's only sanctioned homes are `changelog.md` + frozen `prior_*`; `todo.txt`
  is **USER-ONLY** (agent never reads/touches it).
- Scrub pass: `implementation_plan.md` stale references to removed launcher
  machinery reworded (entrypoint-only wording); live docs grep-clean.

## [HS_HPA rejection root-caused: Tensile GLVW==VW-or-1 generator guard; guard-legal configs found] 2026-09-19

- **Exact rejection isolated** (driver scratch `/tmp/opencode/e2e_hpa` +
  `PrintSolutionRejectionReason`): stock Tensile non-MI assembly guard
  `GlobalLoadVectorWidth{X} must be == VectorWidth or == 1`
  (`SolutionStructs.py:4583-4596`; source comment: "Restrict GRVW/VW combos so
  shift-ptr logic will work"). Fires when `setGlobalLoadVectorWidth`
  (`:2010-2047`) pv-reduces GLVW 4→2 for 64x64x8/TT4x4/VW4 tabs
  (totalElements 512 < NumThreads·GLVW = 1024, pv=2). The predicate is
  **isa-independent** (rejects gfx900 identically) — a generator/representation
  restriction, NOT a gfx90c HW/ISA limit and NOT an assembler failure.
- **Same HS_HPA intent admitted by stock Tensile on native gfx90c:**
  - MT64x64x16/TT4x4/VW4/DU16 → `1/1 after SolutionStructs`; gfx90c kernel
    assembles (`Kernels.so-000-gfx90c.hsaco`, `TensileLibrary_gfx90c.co`).
  - MT64x64x8/TT4x4/VW2/DU8 → `1/1 after SolutionStructs` and `1/1 after
    KernelWriter`.
- The 0-solution HS_HPA registry records are a parameterization collision with a
  Tensile generator guard (not a hardware incapacity); HS_HPA tuning resumes on the
  two guard-legal parameterizations.
- **Fix (pending):** scheduler `_validate_tensile_loads` lacks the `GLVW==VW-or-1`
  predicate under which the 64x64x8 deck fails — add it to the mirror.
- Docs updated: `potential_configs.md` §4 + §5.3 item 7, `implementation_plan.md`
  technical findings.

## [Native .env + toolchain resolution (industry standard) — custom chains removed] 2026-09-19

- **`.env` loading → `python-dotenv` `load_dotenv()`** (industry standard; never
  overrides live env). The hand-rolled `_load_dotenv` parser and the
  `*_CANDIDATES`/`_first_existing_*` probe chains are gone from
  `port_tensile.py`; `requirements.txt` adds `python-dotenv`.
- **ROCm discovery → native tools only:** `hipconfig` (ROCM_PATH/HIP_PATH/
  HIP_CLANG_PATH) + `shutil.which` for binaries on PATH. `.env` and README §6
  slimmed to `TENSILE_ROOT` + optional overrides; no candidate chains.
- **Guardrail added to `claude.md` §5:** never re-invent known-solved problems —
  OS/stdlib/industry-standard library wins (`.env`→python-dotenv,
  discovery→`hipconfig`+`shutil.which`, locks/DB→stdlib, CLI→`argparse`).
- **Validated:** Phase-0 preflight 4/4 and a suite-exact ActiveE2E
  (`phase_ss_Ailk_Bjlk_256x256x256_mt96x96x16_tt6x6`, rc=0, Actual Solutions 1/1,
  `TensileLibrary_gfx90c.co` + `Kernels.so-000-gfx90c.hsaco`) with the native
  resolution (scratch `/tmp/opencode/e2e_b`, isolated).

## [Docs ecosystem governance: shim & legacy-suite silence, todo.txt user-only] 2026-09-19

- **Rule codified in `claude.md` §8.1:** the import-time shim no longer exists and
  is never mentioned in code, docs, or prose; its history lives only in this
  changelog and the frozen `prior_*` files. The prior-campaign shell suite
  (`run_gfx90c_suite.sh`) is referenced only inside `prior_*`.
- **`todo.txt` is a user-only file:** the agent never reads, writes, or touches it.
- **`claude.md` native-support wording aligned** to "2-file minimal Tensile patch"
  (`Tensile/Common.py` + `Tensile/AsmCaps.py`).

## [Distro-agnostic ROCm toolchain resolution] 2026-09-19

- **`.env` fleshed out for both install styles:** ROCm paths are now probed via
  `*_CANDIDATES` ':'-chains (`ROCM_PREFIX_*`, `ROCM_BIN_*`,
  `ROCM_LLVM_BIN_*`, `TENSILE_ASSEMBLER_*`, `TENSILE_ASSEMBLER_FALLBACK_*`);
  first existing entry wins, so AMD-installer (`/opt/rocm`) and Fedora-RPM
  (`/usr/bin` + `/usr/lib64/rocm`) hosts both work from one `.env`.
- **`port_tensile.py`:** new `_first_existing_dir` / `_first_existing_file` /
  `_resolve_rocm_paths()` used by `_get_tensile_env` (PATH injection + subprocess
  `ROCM_PATH`/`HIP_PATH`) and the `--assembler` selection. Explicit env values
  still win when they point at existing paths; stale values fall back to the chain.
  Verified on live host plus synthetic AMD-only and Fedora-only scenarios
  (`/tmp/opencode/test_rocm_probe.py`).
- **README §6 rewritten** for the candidate-chain schema + fixed the residual
  "28-family coverage metrics" wording on the `report.py` row.

## [Repo relocation & report/driver hygiene] 2026-09-19

- **`file:///` references removed:** docs previously pointed at the dead
  `GPU/backrocm/porting_tensile/attempt2` path; README links now relative.
- **Hardcoded locations → `.env`:** `port_tensile.py` loads `TENSILE_ROOT`,
  `ROCM_*`, `HIP_*`, `TENSILE_ASSEMBLER(_FALLBACK)` from `.env` (shell env >
  `.env` > defaults). `.env` created in repo root.
- **Early-quit key `'e'`:** ends the run cleanly after the current phase /
  iteration (run stays `completed`, metadata `end_after_iteration: true`).
- **Verbose logs:** Tensile stdout/stderr are teed live to console (prefixed
  `[tensile]`) and to `logs/.../stdout.log`/`stderr.log`; `TENSILE_VERBOSE=1`
  appends `--verbose` (Tensile PrintLevel 3).
- **Acceptance report HTML de-hardcoded:** Problem space / coverage matrix /
  telemetry sections are now data-derived (cell analytics, registry
  started→completed timing, `logs/telemetry.csv` medians/peaks). Fabricated
  VRAM / SCLK / MCLK / GPU-busy rows dropped (sensors unavailable on this APU).
- **Report dtype fix:** `extract_dtype_from_phase_id` now uses the token family
  parser (was a regex that returned `'unknown'` for `phase_ss_spoof_baseline_vega10`);
  `'auto'` family mapped to `'S'`. The 67 red cells previously logged as
  dtype `unknown` now resolve to real dtypes.

## [Native gfx90c support replaces the import-time shim] 2026-09-19

- **Root cause of the shim:** Tensile's `populateCapabilities` runs before config
  merge, so a config-parse-time ISA injection is too late; 2026-08–09 proved the only
  shim-compatible hook was import time (`tensile_gfx90c_port/sitecustomize.py` on
  `PYTHONPATH`, 3 injections: `SupportedISA`, `architectureMap`, `getCapabilitiesCache`
  seeded from gfx90 just so gfx90c was not probed-and-rejected).
- **Replaced by real in-tree support** on Tensile latest `develop_deprecated` HEAD
  (verified equal to `origin/develop_deprecated`, `e8a8999e`): 3 minimal bookkeeping
  entries in `Tensile/Common.py` (`SupportedISA` `(9,0,12)`; `architectureMap`
  `gfx90c`/`:xnack+`/`:xnack-`) plus `Tensile/AsmCaps.py`, a first-class `(9,0,12)`
  capability entry written from scratch from LLVM `FeatureISAVersion9_0_C`
  (`HasMadMixInsts`; no MFMA / dot / dl-insts / VOP2-fmac / WMMA / kernarg-preload).
  No cloning or deriving from any other ISA.
- **Validated:** written caps == real assembler-derived gfx90c caps (0 mismatches,
  ROCm 6.4); roundtrip `gfxName((9,0,12))`/`gfxArch('gfx90c')`; `GetArchCaps((9,0,12))`
  needs no change. End-to-end with the driver's own known-good config from
  `phases.yaml` (`phase_ss_Ailk_Bjlk_256x256x256_mt64x64x16_tt4x4_3`): native
  `# Detected GPU 0: gfx90c`, "Actual Solutions: 1 / 1", kernel built, loaded
  `TensileLibrary_gfx90c.co` / `Kernels.so-000-gfx90c.hsaco`, benchmarked 434 GFlops
  @ 256³, exit 0.
- **Shim removed:** `tensile_gfx90c_port/` deleted; `port_tensile.py`
  `_get_tensile_env`/`run_preflight` stripped of shim wiring and `TENSILE_REPO_ROOT`;
  grep-clean across driver modules. Phase-0 preflight passes 4/4 shim-free.
- **Docs updated** (knowledge_base §2/§3, README preflight, mapping, claude.md tree
  + PYTHONPATH, implementation_plan) to describe native support. The "pristine HEAD,
  shim-only" wording in the `Upstream baseline` section above is **superseded** by
  this entry.

## [Phases.yaml Fixes, Telemetry v2 & Client/Bench Split PoC] 2026-09-14

- **`phases.yaml` — 48 Invalid Entries Repaired:** Reconciled NLCA and DepthU divisibility rules via in-place fixes (NLCA 3→1 ×46, DepthU 4→16 ×2); verified all 230 contraction entries pass `_validate_tensile_loads`. Archived backup at `archive/phases_20260914_prefix.yaml`.
- **`telemetry.py` — Minimal Non-Root Sysfs Telemetry:** Extracted sampler into dedicated clean module reading world-readable sysfs (`0644`), correctly resolving `mclk_hz` via `pp_dpm_mclk` parsing (resolving dead 0 mclk bug) and supporting APUs (`power1_input` fallback).
- **Client/Bench Split PoC:** Verified Tensile `--prebuilt-client` mechanism in `/tmp`, eliminating redundant per-phase CMake host client rebuilds.

---


- **`port_tensile.py` — Completion Record Recovery:** Added `end_record_logged` flag + finally-block recovery logging. If Tensile phase completes successfully but normal logging path is interrupted (e.g., Ctrl+C during final processing), the finally block ensures completion record is persisted to registry.
- **Root Cause:** Run 213103 completed phase (PASS in stdout.log, CSVs generated) but only "started" record existed in DB — no "completed" record. Normal logging path may have been interrupted before `append_record()` call.
- **Fix Mechanism:** Flag tracks successful `append_record()` call; finally block checks if result exists but flag is False, then logs completion record with appropriate status.

---

## [Immediate Keypress Listeners + MacroTile Format Fix] 2026-09-13

- **`port_tensile.py` — Raw Mode Keypress Listeners:** Added `tty.setraw()` to both cooldown and phase execution key listeners for immediate 's'/'q' detection without requiring Enter press. Terminal settings restored in finally blocks.
- **`port_tensile.py` — MacroTile Format Fix:** Corrected Tensile MacroTile schema from invalid `[[M0, M1, DepthU]]` to valid `[[M0, M1]]` format. DepthU now emitted as separate ForkParameter. Fixes "Invalid parameter value: MacroTile = [64, 64, 8]" error causing CC/DD phase failures.
- **Root Cause:** Tensile expects 2D array for MacroTile dimensions only; DepthU is a separate parameter, not third array element.

---

## [Report Generation Coverage Fix for Failed Phases] 2026-09-13

- **`report.py` — Family Coverage Detection:** Enhanced `_compute_family_coverage()` dtype matching to properly detect family-specific cells (CC/DD/ZZ) when phases fail during execution, ensuring accurate coverage statistics even when benchmark CSVs are missing due to configuration errors.
- **Root Cause:** Previous implementation only matched dtype (FP64/FP32) but not family names (CC/DD), causing coverage reports to show 0 cells for CC/DD families despite phase execution attempts.
- **Impact:** Reports now correctly reflect attempted phase execution even when Tensile configuration errors prevent CSV generation.

---

## [Multi-Threaded Compilation, MacroTile Schema Fix, Cooldown Key Controls & Immediate Reporting] 2026-09-13

- **`port_tensile.py` — Multi-Threaded Clang Compilation:** Set `CpuThreads` dynamically based on available CPU cores (`min(os.cpu_count(), 16)` instead of forced single-thread `1`), accelerating clang assembly build times.
- **`port_tensile.py` — MacroTile Tensile Schema Fix:** Corrected `ForkParameters` emission from invalid `MacroTile0`/`MacroTile1` keys to valid Tensile top-level list `MacroTile: [[M0, M1, DepthU]]` (resolving the `Invalid parameter name: MacroTile0` error in CC/DD runs).
- **`port_tensile.py` — MacroTile0/MacroTile1 Removal:** Added explicit removal of deprecated `MacroTile0`/`MacroTile1` keys from `fork_params` before YAML emission, ensuring Tensile only receives valid `MacroTile: [[M0, M1, DepthU]]` format.
- **`port_tensile.py` — Real-Time Cooldown Key Listeners:** Updated `_apply_cooldown()` to listen for `'s'` (skip cooldown immediately) and `'q'` (gracefully quit run) during thermal sleep.
- **`port_tensile.py` — Immediate Report Generation on Quit:** Ensured `acceptance_report.json` and `acceptance_report.html` are automatically generated and written to `gfx90c_results/` even on early termination via `'q'` or interruption.
- **`README.md` — Usage Documentation:** Added complete documentation for keyboard controls (`s`, `q`), semantic CLI filters (`--family`, `--pattern`, `--shape`), and HTML visual dashboard inspection.

---

## [HTML Dashboard Generator Porting & Integration] 2026-09-13

- **`report.py` — Automated HTML Dashboard:** Ported and unified the attempt1 analytics dashboard generator (`make_report.py`) directly into `AcceptanceReporter.write_html_report()`.
- **Key Features:** Emits dependency-free, responsive dark-mode HTML dashboard (`gfx90c_results/acceptance_report.html`) containing 28-family footprint progress, realistic GEMM ceiling progress bars, per-cell A/B head-to-head comparison cards, and RED-list tracker.
- **Verification:** Tested in `/tmp` POC then integrated into `report.py` and validated with live data.

---

## [Complete 7-Stage Driver Transition & Semantic Target Interface] 2026-09-13

- **`port_tensile.py` — Semantic Target Filtering:** Replaced arbitrary numeric phase arguments with first-class semantic CLI flags: `--family` (`{CC, DD, ZZ, HH, HH_HPA, HS_HPA, SS}`), `--pattern` (`{Ailk_Bjlk, Ailk_Bljk, Alik_Bjlk, Alik_Bljk}`), `--shape`, `--stage` (`1..7`), and `--targets`.
- **`phases.yaml` — 28 Native Families Populated:** Manifest completely populated with 228 clean targets spanning all 28 mathematical contraction families with anchor problem shapes.
- **Dry-run validation:** Added `--dry-run` to query and verify target matching without triggering GPU execution.

---

## [Tensile YAML Generator Fix, Candidate Tile Validation & CSV Resilience] 2026-09-13

- **`port_tensile.py` — `_write_phase_config` fixed:** Corrected `TransposeA`/`TransposeB` derivation from contraction pattern labels (`Ailk_Bljk` $\to$ NN/FF, `Ailk_Bjlk` $\to$ NT/FT, `Alik_Bljk` $\to$ TN/TF, `Alik_Bjlk` $\to$ TT/TT); fixed `MacroTile0`/`MacroTile1` mapping from string representation; calculated `WorkGroup` dynamic tile ratios; enabled `HighPrecisionAccumulate` and mixed precision `DestDataType`/`ComputeDataType` for HPA families.
- **`scheduler.py` — candidate tile divisibility & workgroup validation:** Added validation check in `validate_config` ensuring `MacroTile` dimensions are strictly divisible by `ThreadTile` dimensions (`MacroTile0 % ThreadTile0 == 0`) and workgroup thread count is a multiple of 64 within $[64, 1024]$.
- **`analytics.py` — CSV header whitespace resilience:** Updated `load_benchmark_csv` with whitespace-stripped fieldname parsing and robust per-kernel GFlops metric extraction for space-padded Tensile CSVs.
- **Verification:** Unit tests passing 100%; benchmark CSV parser validated against 96 real kernel measurements (`run_144805`, `run_150517`, `run_151227`) showing peak 928.0 GFlops at $1365^3$.

---

## [Ctrl+C signal handler + stale-run cleanup + run status fix] 2026-09-13

- **`port_tensile.py` — Ctrl+C signal handler fixed:** `_signal_handler` now calls
  `sys.exit(130)` after killing the child process group via `os.killpg`. Previously the
  handler only set `_stop_requested=True`; the driver continued running normally after
  killing the subprocess instead of terminating. Exit code 130 = standard shell Ctrl+C.
  Run status is written to registry as `interrupted` before exit.
- **`registry.py` — `cleanup_stale_runs()` added:** bulk-UPDATE of any `status=started`
  rows to `interrupted` on driver init. Cleans up 3 orphaned runs from this session
  (run_140507, run_141220, run_143006 all set to `interrupted`). Non-destructive: only
  updates status column, does not touch records.
- **`port_tensile.py` — run status semantics:** `run_phases()` now marks run as
  `interrupted` if `_stop_requested` is True at completion, instead of always writing
  `completed`. The `run_auto()` path unchanged (it also sets `_stop_requested` on budget
  exhaustion, which is expected termination — status remains `completed`).
- **Root cause of HipClangVersion failures clarified:** `ValueError: invalid literal for
  int() with base 10: '<unknown>'` in runs 143115–144714 was a pre-symlink race: the
  `/opt/rocm/share/hip/version` symlink did not exist at run time. Symlink was created
  during the session; run_144805 succeeds with `HipClangVersion=6.4.43484`. Code not
  modified; environment is now stable.

---

## [attempt2 driver full remediation & adversarial review fixes] 2026-09-13

- **Full adversarial review remediation across the driver ecosystem:**
  - `port_tensile.py`: Fixed Stage 7 A/B test logic error (no longer passing identical datasets for native and spoof arms); added background continuous sysfs telemetry sampler (`TelemetrySampler` reading `hwmon[0-9]*`, logging canonical `Hz/µW/mC/%` with header-in-CSV); added interactive non-blocking `'s'` skip and `'q'` quit key listeners during phase execution; replaced Stage 6 stub with real YAML logic generator, `TensileCreateLibrary` runner, anti-alias scanner (0 gfx900/vega10 leaks), and 3,066 kernel regression check; eliminated subprocess pipe buffer deadlocks by logging to disk.
  - `scheduler.py`: Corrected GEMM LDS memory estimation to `(M*K + N*K) * elem_size * NLCA / 1024.0`; made `parse_tensile_shape` robust to batch (`_B16`) and explicit K (`_K4096`) shapes; improved wave-based CU occupancy estimation.
  - `agent.py`: Upgraded `converged()` to enforce the full 4-condition convergence standard (≥2 independent runs, ≥3 configs tested, ≤1% movement, and no RED cells); replaced hardcoded FP32 candidate reconstruction fallback with family-aware defaults.
  - `registry.py`: Protected `append_phase()` with `INSERT OR IGNORE` and transaction deduplication to avoid SQLite uniqueness conflicts.
- **Verification:** Unit tests and module import validations pass 100%.

---

## [attempt2 spec drift cleanup + Tensile bulk purge] 2026-09-13

**Spec drifts fixed (SD-1 through SD-7) — all imports now correct:**
- `port_tensile.py`: removed `import fcntl`; fixed docstring (flock→sqlite3 INSERT);
  `AppendOnlyRegistry` → `SQLiteRegistry`; `CandidateGenerator` now receives registry;
  `_extract_phase_number` uses regex `phase_(\d+)` (not naive split); `import re` added.
- `agent.py`: `from scheduler_fixed import` → `from scheduler import`.
- `report.py`: `from policy_fixed import` → `from policy import`.
- `scheduler.py`: `registry` param now optional (`=None`); `append_to_phases` raises
  `RuntimeError` if called without registry instead of silent crash.
- `analytics.py`: stale `fcntl.flock` docstring updated to `sqlite3 records INSERT`.
- All 7 modules import cleanly; `port_tensile.py --help` passes.

**Bulk cleanup — 35.5 GB freed from Tensile working dir:**
- `gfx90c_runs/` (34 GB), `gfx90c_results/` (1.5 GB), `build_tmp/` (75 MB) deleted.
- attempt1 SHA256-verified as complete frozen backup before deletion. Untouched.
- `/tmp/opencode/` retained by user request; purged on next reboot.

**Source of truth confirmed:** PEAK_GFLOPS values match between Tensile and attempt2 mirrors.

---

## [attempt2 persistence: SQLite approved] 2026-09-13

- **Approved change:** ledger write path is stdlib `sqlite3`
  (`gfx90c_results/registry.db`, WAL). `records` = INSERT-only `json.dumps`
  payloads. Replaces `fcntl.flock` + JSONL **as the write path**.
- **Unchanged:** append-only evidence law (`knowledge_base.md` §10); `phases.yaml`
  remains the data-only manifest; harvest still appends YAML rows; stats pipeline
  still consumes run-dir CSV (jsonl export optional until pipeline reads SQLite);
  legacy jsonl files stay on disk, never rewritten.
- **`runs` table:** operational checkpoint (status UPDATE allowed). Not evidence.
- **Retracted:** previous `[attempt2 v1 fixes implementation]` block. That entry
  claimed policy/scheduler/report/agent/driver "fixes" had landed. They had not
  (broken imports, Tensile stub, harvest inverted, RED vs 50% PEAK, YAML
  abolished in the "fixed" driver). Unapproved drifts live in
  `incomplete_work.md` §4.9 / `adversarial_review.md` §6. Do not treat
  `/tmp/opencode/*_fixed.py` as the spec.

## [attempt2 stage approval] 2026-09-13

- **All 7 driver stages approved by user:** Stage 1 (Manifest & Phase Execution), Stage 2 (Candidate Generation), Stage 3 (Benchmark Execution), Stage 4 (Adaptive Repeat / Convergence), Stage 5 (Analytics & Append-Only Registry), Stage 6 (Synthesis / Build), Stage 7 (Acceptance A/B & Final Report).
- **ASCII flowchart added to implementation_plan.md:** Visual representation of stage flow and convergence loops, including the convergence check loop (harvest → mutate ≤2 knobs → loop back to Stage 2) and --auto mode budget-controlled loop.
- **Stage specs now authoritative:** implementation_plan.md Driver Architecture section is the single source for all stage mechanics, scope, key files, and convergence logic.

## [attempt2 consolidation] 2026-09-13

- **Stage specs consolidated into implementation_plan.md:** Previous agent's Stage 4/6/7 functional specs (adaptive repeat/convergence, synthesis/build, acceptance A/B) integrated into Driver Architecture section. Stage 5 (analytics/registry) mechanics added. D2.4 decision recorded: 3 premature auto-retire records (p12 387d2577, p5 286b940a, p6 1570d91a) stay as ordinary rows awaiting ≥2-run corroboration, never marked as verdicts.
- **Core strategy and AI constraints added to implementation_plan.md:** One-shot deterministic convergence flow, AI Must Not Decide rules, Correctness Gate, Reward Hacking prevention, Manual-LLM contingency (user-invoked, add-only, ≤5 candidates). Content consolidated from separate tuning context MD.
- **README.md streamlined:** Removed duplicated hardware/target specifications (now in knowledge_base.md only). Kept orientation, philosophy, goal statement, and file locations.
- **todo.txt removed:** Task list content already in scratch.md; eliminated redundancy.
- **benchmark-retirement-sensor-logging-fixes.json retained:** 19MB session log kept for reference (user declined deletion).
- **tensile_tuning_context.md retained:** Tuning philosophy content consolidated into implementation_plan.md; original file kept for reference (user declined deletion).

## [attempt2 init] 2026-09-13

- New ecosystem folder created at `porting_tensile/attempt2/`; prior-campaign
  conclusions absorbed into `prior_INSIGHTS_CAVEMAN_ULTRA.md` /
  `prior_RESEARCH_ARCHIVE.md` (the ONLY sanctioned prior material, appended no-data-
  deletion).
- **One-shot deterministic convergence contract** authored: no LLM consultation in
  the loop; deterministic harvest → mutate ≤2 knobs → re-run until convergence.
  The ONLY exception is the user manually invoking an LLM to ADD candidate configs
  — add-only, out-of-band, never in the loop.
- **Contract sharpened (2026-09-13, user directive):** attempt2 exists to **beat the
  gfx900 spoof baseline across the entire shipped kernel suite** AND approach the
  gfx90c theoretical limit as closely as possible. The theoretical limit is fixed by
  `gfx90c_theoretical_limits.md` (rocminfo + first-party cross-checked; see that file).
- **Driver architecture folded into `implementation_plan.md`** (single self-contained
  plan): `port_tensile.py` + `phases.yaml` manifest, `json.dumps` state,
  `fcntl.flock` locking, `argparse`, single-source PEAK.
- **Every code change PoC'd in `/tmp/opencode/` until fully functional** before it
  lands anywhere near the live driver (enforced in `implementation_plan.md`).
- **No `changes_kb.md`** — absorbed here. **No `proposed_fixes.md` / `refactor_suite.md`
  / `CHANGELOG.md` / agent-log MDs** — absorbed into `implementation_plan.md` /
  `changelog.md`. Ecosystem is the lean single-owner set registered in `claude.md`.
- Peak table corrected everywhere to single-rate **1613** for BF16 and INT8 (NO
  RDNA-style 3226 assumption); single source `gfx90c_common.PEAK_GFLOPS`.
- `PHASE_TIMEOUT_S` default planned as finite (runaway protection), not unbounded.
- Interactive single-phase kill ('s' skip / 'q' quit — one phase, not the whole run)
  planned for the driver.
- Stats/HTML pipeline retained and carried forward (`all_runs_dataset.py` →
  `make_results_md.py` → `make_report.py` → `gfx90c_report.html`).

## Prior campaign 2026-09-04 .. 2026-09-13 (frozen conclusions)

- Port mechanics proven YES: 3-injection shim, Phase-0 gates 10/10, anti-alias
  0 gfx900 leak, synthesis PASS.
- Performance = **parity, not wins** on the only same-run head-to-head
  (0 win / 11 tie / 0 loss at ±5% vs the gfx900 spoof).
- Candidate suite A–G brought to **5W / 10T / 6L** over 21 shared cells
  (B GEMV 32/64×4096 +8.1/+13.6% & +17.8/+21.3%; D 2048³ +14.1/+20.1%; E int8 1024³
  +18.3%; A sgemm 2048³ stable; F = 3 new cells; C crashed every run until the
  `[{}]` fix).
- Only 6 genuinely-new problem cells produced; ~40% of prior runtime went to
  re-benchmarking known shapes.
- Best measured: FP32 1118.7 @1024³, FP16 2492.1 @4096³, BF16 1108.5 @2048³,
  INT8 881.2 @2048³, FP64 98.6 @1024³ (98% of the 101 pipe — saturated).
- Four ruler bugs found and fixed; three-tier retirement scheme in place;
  telemetry fixed to the sysfs contract; toolchain-stderr fix landed (the single most
  impactful prior change).
- Summary only here — the full conclusion detail lives in
  `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

---

## Prior-campaign evolution (the WHY layer)

### The port mechanism flipped

- Baseline started as a **9-file in-tree patch**; worked, but forked-the-tree drift.
  Replaced by the **3-injection Python shim**
  (`tensile_gfx90c_port/sitecustomize.py` on `PYTHONPATH`): tree stays pristine, the
  whole delta is one import-time file. The shim is the ONLY port mechanism.

### Suite evolution (driver generations)

- The driver suite iterated through several generations during the prior campaign;
  the last shell generation is frozen and inherited as the attempt2 baseline for
  migration parity (new driver paradigm — the attempt2 python driver replaces it).

### Ruler bugs (all four closed prior)

- Ruler normalization was wrong in four ways: max-anchored squares, cross-dtype
  geo-mean leaking the DDR factor, a dtype-string key no-op, and missing rulers
  fabricated as 1.0. Fixed to bound-class medians, `(dt,cls)` keyed, missing →
  **reported, never inferred**. The ruler/throttle discipline only became trustworthy
  once all four were closed.

### Retirement

- Three-tier retirement introduced. Tier-1 = identical-fp skip (default on; opts out
  via a config flag; `--phases` scoped). Tier-2 = dominance retirement by
  `auto_retire.py` (attempt2 gates on ≥2 independent runs/cell after a premature
  3-record emission). Tier-3 = peak/spoof never retires anything.

### Telemetry

- Fixed to the sysfs contract; `logs/telemetry.csv` carries its header in-file
  (self-describing; canonical Hz/µW/mC/%, `hwmon[0-9]*`, `power1_input` →
  `power1_average` fallback). Continuous whole-run sampler, 2 s cadence.

### The single most impactful fix

- **Toolchain stderr fix** — the single most impactful change of the prior campaign:
  tool stderr kept out of machine-readable outputs made the append-only result stream
  trustworthy. Every downstream pipeline depends on it.

---

## 2026-09-28 — Occupancy preflight gate; ZZ dead tiles replaced

**Why.** All 8 executed native ZZ phases (`run_20260926_201835`) ended
`Generating kernel source resulted in error 4` = `overflowedResources == 4`
= Tensile's *Occupancy limit* (register-file exhaustion, `KernelWriterAssembly.py:15422`),
not a launch failure and not the benign "error 3". They died because the
legality preflight **could not detect this class of failure at all**:
`_estimate_occupancy` inferred the thread count from `ThreadTile` via a
`64 // tt` heuristic, ignored `MacroTile` entirely, and never counted VGPRs —
so it returned ≥ 1 for every config and never fired.

**What changed.**

- `scheduler.py`: added `VGPR_PER_ELEMENT`, `VGPR_BUDGET`, `_tile_dims`,
  `_dtype_char`, `occupancy_workgroups_per_cu`, `occupancy_feasible`.
  `validate_config` and `_estimate_occupancy` both delegate to the one model, so
  there is a single source of truth. The gate **fails closed** on a dtype with no
  VGPR weight: a low guess (S=1) would re-admit a failure that a high guess (Z=8)
  catches.
- `phases.yaml`: 410 → 418. Removed the 8 dead phases (`MT 128x64x8/8x4` and
  `MT 64x128x8/4x8` × 4 contraction patterns); added 16 legal ones:
  `128x32x8/8x4` and `32x128x8/2x8` as same-aspect replacements, plus `64x64x8/4x2`
  (thread count never varied for ZZ) and `128x32x16/8x4` (deeper K). Phase IDs and
  SHA-256 fingerprints regenerated; uniqueness asserted. The pre-fix deck is kept at
  `archive/phases.yaml.pre-occupancy-gate.bak` as regression evidence.
- New `check_candidates.py`: sweeps any deck through the 4 gates
  (divisibility, assembly-class, LDS, occupancy), exits 1 on any illegal config,
  so an illegal deck can be caught before a GPU run instead of mid-run.
- New `allruns.py`: all-runs pattern analysis over the whole DB, driving oto's own
  loaders (`_native_records_all_runs`, `_ab_records_from_csv`,
  `compute_native_vs_spoof_delta` winner semantics) so it cannot drift from the
  pipeline that produced the ledger.
- New `test_occupancy_gate.py`: 18 tests, incl. the calibration matrix, the
  ThreadTile-cancels identity, fail-closed dtype behaviour, the shipped deck being
  legal, and the pre-fix deck still failing exactly 8.

**Verification (CPU only, no Tensile launch, no GPU).** 18/18 tests pass;
`check_candidates.py` reports 0 illegal across all 418 shipped phases and exactly 8
illegal against the archived pre-fix deck.

**Honest limits.** The weights are **calibrated, not derived**: `R=8` for ZZ is the
smallest value reproducing every observed outcome, and the gate demands 2× headroom
because the raw accumulator-only count predicts `numWorkGroupsPerCU == 1` for the
tile that actually died (pinned in `test_raw_tensile_model_would_have_missed_the_failure`).
It reproduces all 9 observed cases and has zero false positives over 410 phases, but
it is a model, not a register allocator. ZZ is now **legal but unbenchmarked** — the
next step for the family is a TTY run, not more code.

---

## Session / consultation record

- **Prior campaign consumed 3 of 6 in-session LLM consultations.**
- **attempt2 consumes 0 by design.** The deterministic pipeline replaces the
  prior candidate-sweep loop entirely; a consultation would only be sanctioned to
  break a coverage deadlock — as a USER-invoked, add-only candidate injection (single
  canned prompt, ≤5 recipe mutations constrained to known-valid gfx90c knobs, dropped
  into `phases.yaml`). Never automatic; never in the loop.

## Upstream baseline

- The live Tensile repo remains at pristine HEAD, read-only, only the gfx90c shim
  applied. No upstream release entries are mirrored here.