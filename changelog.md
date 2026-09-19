# Changelog — Tensile gfx90c port

The SINGLE changelog/evolution log for the project. One fact, one canonical home:
milestone + rationale entries land here; they are never re-created elsewhere.
Prior-campaign conclusions are sourced (never copied) from the two sanctioned
prior MDs: `prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`.

This file records project milestones and the prior-campaign → attempt2 evolution
narrative, NOT the active implementation state (that is `implementation_plan.md`)
and NOT the experimental data (that is `results.md`).

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